# Command line entry point: parse targets, open tunnels, print the index QR.

import argparse
import asyncio
import os
import signal
import sys

from . import config, qr
from .service import Portal


def build_parser():
    parser = argparse.ArgumentParser(
        prog="portal",
        description="Publish local ports as tokenised Cloudflare tunnels.",
    )
    parser.add_argument("--port", type=int, action="append", default=[],
                        help="local port to publish (repeatable)")
    parser.add_argument("--config", default=None,
                        help="config file with [[target]] entries (default: ./config.toml if present)")
    parser.add_argument("--token", default=None,
                        help="fixed capability token instead of a random one")
    return parser


def _banner(portal):
    print(f"portal   {len(portal.urls)}/{len(portal.targets)} 个端口已上线")
    for target in portal.targets:
        url = portal.urls.get(target.port)
        if url is None:
            print(f"  {target.port:<6}  {target.name or '未命名':<10} 隧道未建立")
            continue
        print(f"  {target.port:<6}  {target.name or '未命名':<10} {url}")
    print(f"索引     {portal.index_url}")
    print("提示     链接即权限，谁拿到链接谁就能用；进程退出后链接和 token 一起失效。")
    print()
    print(qr.to_terminal(portal.index_url), flush=True)


def _resolve(args):
    targets = []
    path = args.config
    if path is None and os.path.exists("config.toml"):
        path = "config.toml"
    if path is not None:
        targets = config.load(path)
    return config.merge(targets, args.port)


async def _run(portal):
    await portal.start()
    for target, message in portal.failures:
        print(f"portal: 端口 {target.port} 的隧道建立失败：{message}", file=sys.stderr)
    if not portal.urls:
        await portal.stop()
        print("portal: 没有可用的隧道，退出。", file=sys.stderr)
        return 1
    _banner(portal)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (ValueError, NotImplementedError):
            pass
    try:
        await stop.wait()
    finally:
        await portal.stop()
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        targets = _resolve(args)
    except config.ConfigError as exc:
        print(f"portal: {exc}", file=sys.stderr)
        return 2
    if not targets:
        print("portal: 没有指定端口，用 --port 或在 config.toml 里写 [[target]]。", file=sys.stderr)
        return 2
    portal = Portal(targets)
    if args.token:
        portal.auth.token = args.token
    try:
        return asyncio.run(_run(portal))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
