# weave

Share Claude Code sessions between machines over a simple HTTP hub. Weave moves the conversation, not git.

Package: `weave-sessions` (Python ≥3.11, no runtime deps). Commands: `push`, `pull`, `rm`, `remote add`, `ls`, `log`, `help`.

## Install

Mac or Linux, Python 3.11+, and `git` (for install from GitHub). The repo is private — use GitHub auth:

```bash
gh api -H "Accept: application/vnd.github.raw" \
  repos/lindsay-cheng/weave/contents/install.sh | bash
```

Checks only (no install): pipe to `bash -s -- --check` instead of `bash`.

With [pipx](https://pipx.pypa.io/) already on PATH, the installer uses it; otherwise `pip install --user` and prints the user `bin` dir to add to PATH.

Verify: `weave help` · `weave --version`

Once a landing page is hosted publicly: `curl -fsSL https://YOUR_HOST/install.sh | bash`

## Quick start

Run a hub (see [HUB.md](HUB.md) for Python or Docker). Set `WEAVE_HUB_PASSWORD` in the environment — never in `.weave/config`.

```bash
export WEAVE_HUB_PASSWORD=your-secret
weave-hub --dir /path/to/chats    # http://127.0.0.1:8080
```

In your project:

```bash
weave remote add origin http://localhost:8080
weave push origin auth-refactor          # one local chat, or --session <id> if several
weave pull origin auth-refactor -o       # -o runs claude --resume when claude is on PATH
weave ls origin
```

First `weave remote add` creates `.weave/config` in the current folder. After that, weave walks up to find it. Session names: letters, numbers, hyphen; lowercase; reusing a name is an error.

## Your repo

Commit `.weave/config` so teammates get the remote. Ignore the log:

```gitignore
.weave/log
```

## Hub password

`WEAVE_HUB_PASSWORD` — see [.env.example](.env.example). Hub details: [HUB.md](HUB.md).
