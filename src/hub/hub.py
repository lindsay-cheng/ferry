"""Stdlib HTTP hub: named chats as files in a folder.

One shared password from ``FERRY_HUB_PASSWORD``. Names are letters, numbers,
and hyphen, stored lowercase. Same name twice is an error. Do not point
``--dir`` at ``~/.claude``.
"""

import argparse
import errno
import hmac
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

_NAME_RE = re.compile(r"[a-z0-9-]+")
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8080
_ENV = "FERRY_HUB_PASSWORD"


def normalize_name(name):
    n = (name or "").lower()
    if not _NAME_RE.fullmatch(n):
        raise ValueError("name must be letters, numbers, and hyphen")
    return n


def _handler(data_dir, password):
    data_dir = Path(data_dir).resolve()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def _ok_auth(self):
            got = self.headers.get("Authorization", "")
            want = f"Bearer {password}"
            try:
                good = hmac.compare_digest(got, want)
            except (TypeError, ValueError):
                good = False
            if not good:
                self._text(401, "bad password")
            return good

        def _text(self, code, body):
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _name(self):
            raw = unquote(urlparse(self.path).path).strip("/")
            if not raw:
                return None
            if "/" in raw:
                raise ValueError("name must be letters, numbers, and hyphen")
            return normalize_name(raw)

        def _file(self, name):
            return data_dir / f"{name}.jsonl"

        def do_GET(self):
            if not self._ok_auth():
                return
            try:
                name = self._name()
            except ValueError as e:
                self._text(400, str(e))
                return
            if name is None:
                names = sorted(p.stem for p in data_dir.glob("*.jsonl") if p.is_file())
                raw = json.dumps(names).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return
            path = self._file(name)
            if not path.is_file():
                self._text(404, f"no session {name!r} on remote")
                return
            raw = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_PUT(self):
            if not self._ok_auth():
                return
            try:
                name = self._name()
            except ValueError as e:
                self._text(400, str(e))
                return
            if name is None:
                self._text(400, "name must be letters, numbers, and hyphen")
                return
            path = self._file(name)
            if path.exists():
                self._text(409, f"name {name!r} already exists")
                return
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length)
            try:
                path.write_bytes(body)
            except OSError as e:
                self._text(500, "disk full" if e.errno == errno.ENOSPC else str(e))
                return
            self._text(201, "created")

        def do_DELETE(self):
            if not self._ok_auth():
                return
            try:
                name = self._name()
            except ValueError as e:
                self._text(400, str(e))
                return
            if name is None:
                self._text(400, "name must be letters, numbers, and hyphen")
                return
            path = self._file(name)
            if not path.is_file():
                self._text(404, f"no session {name!r} on remote")
                return
            path.unlink()
            self.send_response(204)
            self.end_headers()

    return Handler


def make_server(data_dir, password, host=_DEFAULT_HOST, port=_DEFAULT_PORT):
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), _handler(data_dir, password))
    httpd.allow_reuse_address = True
    return httpd


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="ferry-hub",
        description=(
            "Serve a folder of named chats over HTTP. "
            "Set FERRY_HUB_PASSWORD. Default http://127.0.0.1:8080. "
            "Names are letters, numbers, and hyphen; stored lowercase."
        ),
    )
    p.add_argument("--dir", required=True,
                   help="folder to store chats (not ~/.claude)")
    p.add_argument("--host", default=_DEFAULT_HOST)
    p.add_argument("--port", type=int, default=_DEFAULT_PORT)
    args = p.parse_args(argv)
    # hub reads the process env; the CLI autoloads .env
    password = os.environ.get(_ENV, "")
    if not password:
        print(f"ferry-hub: set {_ENV}", file=sys.stderr)
        return 1
    httpd = make_server(args.dir, password, args.host, args.port)
    print(
        f"ferry-hub: http://{args.host}:{httpd.server_port}  "
        f"dir={Path(args.dir).resolve()}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 0
    finally:
        httpd.server_close()
    return 0
