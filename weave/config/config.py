import configparser
import json
import os
from pathlib import Path

DEFAULT_PATH = ".weave/config"

_NOT_A_PROJECT = (
    "not a Weave project — run: weave remote add <name> <url>")


def _find_config(start_dir=None):
    """Walk up from start_dir (default cwd) for an existing ``.weave/config`` file."""
    d = Path(start_dir or os.getcwd())
    while True:
        candidate = d / DEFAULT_PATH
        if candidate.is_file():
            return candidate
        parent = d.parent
        if parent == d:
            return None
        d = parent


def _config_path(path, *, create=False):
    """Resolve the config file path.

    Explicit ``path``: use that file (may not exist yet). ``path`` is ``None``:
    walk up from cwd; when ``create`` and none found, target ``cwd/.weave/config``.
    """
    if path is not None:
        return Path(path)
    found = _find_config()
    if found is not None:
        return found
    if create:
        return Path(os.getcwd()) / DEFAULT_PATH
    raise ValueError(_NOT_A_PROJECT)


def project_dir(*, path=None):
    """Return the Weave project folder (the directory that contains ``.weave``)."""
    return _config_path(path).parent.parent


def _read_cfg(cfg_path):
    cfg = configparser.ConfigParser()
    if cfg_path.is_file():
        cfg.read(cfg_path, encoding="utf-8")
    return cfg


def _log_path(path):
    """Operation log lives next to the config file (``.weave/log``)."""
    return _config_path(path).parent / "log"


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


def _write(cfg, cfg_path):
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    with cfg_path.open("w", encoding="utf-8") as f:
        cfg.write(f)


def add_remote(name, url, *, path=None):
    cfg_path = _config_path(path, create=(path is None))
    cfg = _read_cfg(cfg_path)
    section = f'remote "{name}"'
    if cfg.has_section(section):
        raise ValueError(f"remote {name!r} already exists")
    cfg.add_section(section)
    cfg.set(section, "url", url)
    _write(cfg, cfg_path)


def get_remote(name, *, path=None):
    cfg = _read_cfg(_config_path(path))
    section = f'remote "{name}"'
    if not cfg.has_option(section, "url"):
        raise ValueError(f"no remote {name!r} — run: weave remote add {name} <url>")
    return cfg.get(section, "url")


def list_remotes(*, path=None):
    cfg = _read_cfg(_config_path(path))
    result = []
    for section in cfg.sections():
        if section.startswith("remote "):
            name = section.split('"')[1]
            url = cfg.get(section, "url", fallback="")
            result.append((name, url))
    return result
