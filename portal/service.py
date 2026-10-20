# The portal itself: one proxy and one tunnel per target, plus the shared token.

import asyncio
from urllib.parse import quote

from .auth import Auth
from .proxy import PortProxy
from .tunnel import start as start_tunnel


class Portal:
    def __init__(self, targets, auth=None):
        self.targets = list(targets)
        self.auth = auth or Auth()
        self.proxies = []
        self.urls = {}
        self.failures = []

    async def start(self):
        for target in self.targets:
            proxy = PortProxy(self, target)
            await proxy.start()
            self.proxies.append(proxy)
        results = await asyncio.gather(
            *(start_tunnel(proxy.port) for proxy in self.proxies),
            return_exceptions=True,
        )
        for proxy, result in zip(self.proxies, results):
            if isinstance(result, BaseException):
                self.failures.append((proxy.target, str(result)))
                await proxy.close()
                continue
            proxy.tunnel = result
            self.urls[proxy.target.port] = result.url
        self.proxies = [proxy for proxy in self.proxies if proxy.tunnel is not None]

    @property
    def index_url(self):
        for target in self.targets:
            url = self.urls.get(target.port)
            if url:
                return f"{url}/_portal/?token={quote(self.auth.token, safe='')}"
        return None

    async def stop(self):
        await asyncio.gather(
            *(proxy.tunnel.stop() for proxy in self.proxies if proxy.tunnel is not None),
            return_exceptions=True,
        )
        for proxy in self.proxies:
            await proxy.close()
        self.proxies = []
