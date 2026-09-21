# weave-hub

Named chat files over HTTP. Same push/pull/list/delete the CLI uses via `weave remote`.

## Password

Set `WEAVE_HUB_PASSWORD` in your shell (or `.env` for Docker). Never put it in `.weave/config`.

## Python

```bash
export WEAVE_HUB_PASSWORD=your-secret
weave-hub --dir /path/to/chats
# or: python -m weave.hub --dir /path/to/chats
```

Use a folder you own for `--dir`, not `~/.claude`. Default bind: `http://127.0.0.1:8080`.

## Docker

Copy `.env.example` to `.env`, set `WEAVE_HUB_PASSWORD`, then:

```bash
docker compose up
```

Chats land in `./chats` on the host (bind mount, not a database). Hub listens on `http://localhost:8080`.

To survive reboots: `restart: unless-stopped` in compose, plus enable “Start Docker Desktop when you log in” (or your platform’s equivalent) on the machine that runs the hub.

## Teammates

They do not run Docker. They `weave remote add <name> http://your-hub:8080` and use `weave push` / `weave pull` as usual.
