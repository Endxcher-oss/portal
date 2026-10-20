# One listener per published port: token exchange, index page, transparent proxy.

import asyncio
from html import escape
from urllib.parse import quote, urlsplit

from .http import read_request, respond

HOP_BY_HOP = {"keep-alive", "proxy-connection", "te", "trailer"}

CSP = "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"

INDEX_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>portal</title>
<style>
:root { --bg:#1d1d1d; --fg:#deddda; --panel:#242424; --line:#303030; --muted:#b0afac; --accent:#62a0ea; }
* { box-sizing: border-box; }
body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
  font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size:14px; }
h1 { font-size:12px; letter-spacing:.18em; color:var(--muted); margin:0 0 16px; }
ul { list-style:none; margin:0; padding:0; }
li { margin:0 0 8px; }
a, .off { display:flex; align-items:center; gap:12px; padding:12px 14px;
  border:1px solid var(--line); border-radius:8px; background:var(--panel);
  color:var(--fg); text-decoration:none; }
a:hover { border-color:var(--accent); }
.port { color:var(--muted); min-width:5ch; }
.name { flex:1; }
.go { color:var(--accent); font-size:12px; }
.off { opacity:.45; }
.off .go { color:var(--muted); }
</style>
</head>
<body>
<h1>PORTAL</h1>
<ul>
<!--rows-->
</ul>
</body>
</html>
"""

DENIED_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>portal</title>
<style>
body { margin:0; min-height:100vh; display:flex; align-items:center; justify-content:center;
  padding:24px; background:#1d1d1d; color:#deddda;
  font-family: ui-monospace, "DejaVu Sans Mono", monospace; font-size:14px; text-align:center; }
p { max-width:22em; line-height:1.7; }
</style>
</head>
<body>
<p><!--message--></p>
</body>
</html>
"""


def _strip_token(target):
    parts = urlsplit(target)
    pairs = [item for item in parts.query.split("&") if item and not item.startswith("token=")]
    query = "&".join(pairs)
    return parts.path + (f"?{query}" if query else "")


def _request_head(request, websocket):
    lines = [f"{request.method} {request.target} HTTP/1.1"]
    for name, value in request.headers.items():
        if name in HOP_BY_HOP or name == "connection":
            if not (websocket and name == "connection"):
                continue
        lines.append(f"{name}: {value}")
    if not websocket:
        lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


def _response_head(raw, websocket):
    lines = raw.decode("latin-1").split("\r\n")
    out = [lines[0]]
    for line in lines[1:]:
        if not line:
            continue
        name = line.split(":", 1)[0].strip().lower()
        if not websocket and name in ("connection", "keep-alive"):
            continue
        out.append(line)
    if not websocket:
        out.append("Connection: close")
    return ("\r\n".join(out) + "\r\n\r\n").encode("latin-1")


async def _send_body(request, reader, writer):
    length = request.headers.get("content-length")
    if length:
        try:
            remaining = int(length)
        except ValueError:
            return
        while remaining > 0:
            chunk = await reader.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            writer.write(chunk)
            await writer.drain()
        return
    if "chunked" in request.headers.get("transfer-encoding", "").lower():
        while True:
            line = await reader.readuntil(b"\r\n")
            writer.write(line)
            size = int(line.split(b";")[0], 16)
            if size == 0:
                while True:
                    trailer = await reader.readuntil(b"\r\n")
                    writer.write(trailer)
                    if trailer == b"\r\n":
                        break
                break
            writer.write(await reader.readexactly(size + 2))
            await writer.drain()
    await writer.drain()


async def _copy(source, sink):
    try:
        while True:
            chunk = await source.read(65536)
            if not chunk:
                break
            sink.write(chunk)
            await sink.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def _bridge(client_reader, client_writer, upstream_reader, upstream_writer):
    async def pump(source, sink):
        await _copy(source, sink)
        try:
            sink.close()
        except Exception:
            pass

    await asyncio.gather(
        pump(client_reader, upstream_writer),
        pump(upstream_reader, client_writer),
    )


class PortProxy:
    def __init__(self, portal, target):
        self.portal = portal
        self.target = target
        self.tunnel = None
        self._server = None
        self.port = None

    async def start(self):
        self._server = await asyncio.start_server(self.handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def close(self):
        server, self._server = self._server, None
        if server is not None:
            server.close()
            try:
                await asyncio.wait_for(server.wait_closed(), 5)
            except asyncio.TimeoutError:
                pass

    async def handle(self, reader, writer):
        try:
            request = await read_request(reader)
            if request is None:
                await respond(writer, 400, "bad request")
                return
            token = request.get("token")
            if token:
                if self.portal.auth.matches(token):
                    await self._exchange(request, writer)
                else:
                    await self._denied(writer, "链接无效或已失效，请用启动时打印的新链接。")
                return
            if not self.portal.auth.authorized(request):
                await self._denied(writer, "请用启动时打印的二维码或链接打开。")
                return
            if request.path == "/_portal":
                await respond(writer, 308, b"", extra={"Location": "/_portal/"})
                return
            if request.path == "/_portal/":
                await self._index(writer)
                return
            await self._forward(request, reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:
            try:
                await respond(writer, 500, "portal: internal error")
            except Exception:
                pass
        finally:
            writer.close()

    async def _exchange(self, request, writer):
        extra = {
            "Location": _strip_token(request.target),
            "Set-Cookie": self.portal.auth.cookie("cf-visitor" in request.headers),
            "Cache-Control": "no-store",
        }
        await respond(writer, 303, b"", "text/plain; charset=utf-8", extra)

    async def _denied(self, writer, message):
        page = DENIED_PAGE.replace("<!--message-->", escape(message))
        await respond(writer, 401, page, "text/html; charset=utf-8",
                      {"Cache-Control": "no-store", "Content-Security-Policy": CSP})

    async def _index(self, writer):
        rows = []
        for target in self.portal.targets:
            url = self.portal.urls.get(target.port)
            name = escape(target.name or "未命名")
            if url is None:
                rows.append(f'<li><span class="off"><span class="port">{target.port}</span>'
                            f'<span class="name">{name}</span><span class="go">隧道未建立</span></span></li>')
                continue
            link = escape(f"{url}/?token={quote(self.portal.auth.token, safe='')}")
            rows.append(f'<li><a href="{link}" target="_blank" rel="noopener">'
                        f'<span class="port">{target.port}</span>'
                        f'<span class="name">{name}</span><span class="go">打开</span></a></li>')
        page = INDEX_PAGE.replace("<!--rows-->", "\n".join(rows))
        await respond(writer, 200, page, "text/html; charset=utf-8",
                      {"Cache-Control": "no-store", "Content-Security-Policy": CSP})

    async def _forward(self, request, reader, writer):
        websocket = request.headers.get("upgrade", "").lower() == "websocket"
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection("127.0.0.1", self.target.port)
        except OSError:
            await respond(writer, 503, f"portal: 本地端口 {self.target.port} 没有服务在监听")
            return
        try:
            upstream_writer.write(_request_head(request, websocket))
            await upstream_writer.drain()
            if not websocket:
                await _send_body(request, reader, upstream_writer)
            head = await upstream_reader.readuntil(b"\r\n\r\n")
            writer.write(_response_head(head, websocket))
            await writer.drain()
            if websocket and b" 101 " in head.split(b"\r\n")[0]:
                await _bridge(reader, writer, upstream_reader, upstream_writer)
            else:
                await _copy(upstream_reader, writer)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                upstream_writer.close()
            except Exception:
                pass
