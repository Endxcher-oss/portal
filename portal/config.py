# Published targets: which local ports portal exposes, loaded from TOML and CLI.

import tomllib
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    port: int
    name: str = ""

    @property
    def label(self):
        return self.name or str(self.port)


def load(path):
    file = Path(path).expanduser()
    if not file.is_file():
        raise ConfigError(f"配置文件不存在: {file}")
    try:
        data = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"读不了配置文件 {file}: {exc}") from exc
    entries = data.get("target", [])
    if not isinstance(entries, list):
        raise ConfigError("config.toml 里的 [[target]] 必须是数组")
    targets = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ConfigError(f"[[target]] 格式不对: {entry!r}")
        port = entry.get("port")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
            raise ConfigError(f"target 的 port 必须是 1-65535 的整数: {entry!r}")
        targets.append(Target(port, str(entry.get("name") or "")))
    return targets


def merge(base, ports):
    result = list(base)
    known = {target.port for target in result}
    for port in ports:
        if port in known:
            continue
        known.add(port)
        result.append(Target(port, ""))
    return result
