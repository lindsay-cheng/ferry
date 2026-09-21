# weave

> Git primitives for Claude Code sessions.

Claude Code sessions should travel across machines and engineers as naturally as git commits do. **Weave moves the conversation, not git.**

Package: `weave-sessions` (Python ≥3.11, no runtime deps). Commands: `push`, `pull`, `rm`, `remote add`, `ls`, `log`, `help`.

---

## Install

Mac or Linux, Python 3.11+.

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/weave/main/install.sh | bash
```

Checks only (no install):

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/weave/main/install.sh | bash -s -- --check
```

The installer needs `git` on PATH. With [pipx](https://pipx.pypa.io/) present it uses pipx; otherwise `pip install --user` and prints the user `bin` dir to add to PATH.

If the GitHub repo is private, that curl URL must reach `install.sh` (public repo, or host the same script on your landing page).

Verify: `weave help` · `weave --version`

---

## The problem

Claude Code sessions are trapped on the machine that created them. When two developers work on separate problems, their conversational context lives in two separate JSONL files on separate machines. You cannot hand that context to a colleague without sending a raw transcript they have to read, understand, and re-explain to their own Claude session. You cannot pick up where a teammate left off. You cannot carry another engineer's full reasoning — thinking blocks, failed attempts, tool results — onto your own machine and just keep going.

---

## The solution

Claude Code stores conversations as JSONL at `~/.claude/projects/<encoded-path>/<uuid>.jsonl` (or under `$CLAUDE_CONFIG_DIR` if set). Each line is a JSON object: user and assistant messages, thinking blocks, tool calls and results, plus metadata lines (titles, file-history snapshots, mode, permission-mode).

Weave treats this history as a first-class primitive and gives you push/pull over a shared hub:

- **Push** uploads a local session to a named remote file.
- **Pull** downloads a named session and writes a **new** local JSONL file. Weave rewrites `cwd` and `sessionId` on lines that carry them so Claude can open the session on your machine. Other line types pass through unchanged.
- **Resume** is Claude's job: `claude --resume <id>`, or `weave pull ... -o` to run that for you when `claude` is on PATH.

---

## Hub

Weave shares sessions through a simple HTTP folder: named `.jsonl` files on disk, one shared password in the environment. Set `WEAVE_HUB_PASSWORD` in your shell (or `.env` for Docker). Never put the password in `.weave/config`.

```bash
export WEAVE_HUB_PASSWORD=your-secret
weave-hub --dir /path/to/chats    # http://127.0.0.1:8080
```

See [HUB.md](HUB.md) for Python and Docker setup. Teammates point the CLI at your hub:

```bash
weave remote add origin http://localhost:8080
```

Session names are scoped to the remote, so `auth-refactor` on one hub never collides with another team's.

---

## Commands

| Command | Description |
| --- | --- |
| `weave remote add <name> <url>` | Register a hub URL. Creates `.weave/config` in the current folder. Later commands walk up to find it. |
| `weave push [<remote>] <name> [--session <id>]` | Upload a local session. Omit `--session` when exactly one local chat exists for the project; pass it when several do. |
| `weave pull [<remote>] <name> [-o]` | Download a named session into a fresh local file with `cwd` / `sessionId` rewritten. `-o` runs `claude --resume` when `claude` is on PATH. |
| `weave rm [<remote>] <name>` | Delete a session from the hub. Local files are not touched. |
| `weave ls [<remote>]` | List session names on a remote, or local session ids when no remote is given. Remote `ls` prints names only. |
| `weave log` | Show local history of push / pull / rm operations (newest first). |
| `weave help` | Command reference. |

Session names: letters, numbers, hyphen; stored lowercase. Reusing a name on push is an error.

When exactly one remote is configured, you can omit `<remote>` on push, pull, rm, and ls. With two or more remotes, name the one you mean.

---

## Typical flow

**Handoff** — pick up where a teammate left off:

```bash
# Engineer A (in the project)
weave push origin auth-refactor

# Engineer B (same repo, after clone)
weave pull origin auth-refactor -o
```

---

## Your repo

Commit `.weave/config` so teammates get the remote automatically. Ignore the operation log:

```gitignore
.weave/log
```

---

## Architecture

Runtime code lives under the `weave/` package. The hub is a separate entry point (`weave-hub` / `python -m weave.hub`).

| Module | Responsibility |
| --- | --- |
| `weave.cli` | Argument parsing and CLI marshalling. |
| `weave.core` | Orchestrates push/pull/rm/ls; owns policy (session choice, cwd/sessionId rewrite, config walk-up). |
| `weave.connector` | Local filesystem I/O: session id ↔ JSONL path under `$CLAUDE_CONFIG_DIR` or `~/.claude`. |
| `weave.config` | Resolves `.weave/config` remotes and the local operation log. |
| `weave.remote` | HTTP transport to the hub (`push` / `pull` / `list` / `delete`), keyed by `(url, name)`. |
| `weave.hub` | Standalone HTTP server that serves the chat folder. |

```
weave/         # CLI, core, connector, config, remote, hub
tests/         # unit and integration tests
fixtures/      # sample JSONL for tests
```

---

## Status

Alpha. Push/pull over an HTTP hub with password auth. Python 3.11+, stdlib only for the CLI.
