import configparser
import json
from pathlib import Path

DEFAULT_PATH = ".weave/config"


def _resolve(path):
    return Path(path or DEFAULT_PATH)


def _log_path(path):
    """Operation log lives next to the config file (``.weave/log``)."""
    return _resolve(path).parent / "log"


def append_log(entry, *, path=None):
    """Append one operation record (a dict) as a JSON line to the log."""
    p = _log_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(*, path=None):
    """Return the logged operation records in file (chronological) order."""
    p = _log_path(path)
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _read(path):
    cfg = configparser.ConfigParser()
    p = _resolve(path)
    if p.is_file():
        cfg.read(p, encoding="utf-8")
    return cfg


def _write(cfg, path):
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        cfg.write(f)


def add_remote(name, url, *, path=None):
    cfg = _read(path)
    section = f'remote "{name}"'
    if not cfg.has_section(section):
        cfg.add_section(section)
    cfg.set(section, "url", url)
    _write(cfg, path)


def get_remote(name, *, path=None):
    cfg = _read(path)
    section = f'remote "{name}"'
    if not cfg.has_option(section, "url"):
        raise ValueError(f"no remote {name!r} — run: weave remote add {name} <url>")
    return cfg.get(section, "url")


def list_remotes(*, path=None):
    cfg = _read(path)
    result = []
    for section in cfg.sections():
        if section.startswith("remote "):
            name = section.split('"')[1]
            url = cfg.get(section, "url", fallback="")
            result.append((name, url))
    return result
