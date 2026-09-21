# weave

Weave copies a Claude Code chat from one computer to another. Git still moves the source code. Weave moves the conversation file. Weave is not a merge tool, not a fork tool, and there is no `weave resume`.

Package: `weave-sessions` 0.1.0 (Python 3.11+, no runtime dependencies).

## What you need

- Claude Code already installed and used in the project you want to share.
- macOS or Linux.
- Python 3.11 or newer.
- `git` on your PATH (the installer pulls the package from GitHub).

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/weave/main/install.sh | bash
```

`install.sh` is a small bash script in this repository. The curl command downloads it and runs it in your shell. The script refuses Windows. It checks that Python 3.11+ and `git` are available. If [pipx](https://pipx.pypa.io/) is installed, it runs `pipx install --force git+https://github.com/lindsay-cheng/weave.git`. Otherwise it runs `pip install --user` with the same URL and prints the user `bin` directory to add to PATH.

That installs the `weave-sessions` package, which provides the `weave` and `weave-hub` commands. While this repository is private, the raw GitHub URL for `install.sh` returns 404 unless the repo is public or you host the script elsewhere. If curl fails with 404, clone the repo with your normal GitHub access and run `./install.sh` from the repo root. You can also skip curl and run `pipx install git+https://github.com/lindsay-cheng/weave.git`, which uses your git credentials the same way.

Checks only (no install):

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/weave/main/install.sh | bash -s -- --check
```

If you prefer not to use curl, install the same package directly:

```bash
pipx install git+https://github.com/lindsay-cheng/weave.git
```

Without pipx:

```bash
python3 -m pip install --user git+https://github.com/lindsay-cheng/weave.git
```

Verify:

```bash
weave help
weave --version
```

If `weave` is not found, install pipx or add the user scripts directory to PATH. On many systems that is `$(python3 -m site --user-base)/bin`.

### Upgrade

Re-run the curl installer, or:

```bash
pipx install --force git+https://github.com/lindsay-cheng/weave.git
```

## Two programs

- **`weave`** runs on each laptop. It pushes and pulls Claude Code sessions to a shared hub.
- **`weave-hub`** runs on one computer that stays on. It stores named session files on disk and serves them over HTTP.

Teammates never run Docker for Weave. The CLI is never inside Docker.

## First time as a team

1. Install weave on each machine (curl or pipx).
2. Agree on `WEAVE_HUB_PASSWORD` and share it with anyone who will push or pull.
3. One person starts the hub (`weave-hub` or Docker).
4. In the project folder: `weave remote add origin <hub-url>`.
5. Commit `.weave/config`.
6. Add `.weave/log` to `.gitignore`.
7. Engineer A: run Claude Code in that folder, then `weave push origin <name>`.
8. Engineer B: install weave, set the password, then `weave pull origin <name> -o`.

## Start the hub (once per team)

One person on the team runs the hub. Everyone else only runs `weave`.

### Password

Set `WEAVE_HUB_PASSWORD` in the environment. Never put the password in `.weave/config`. Anyone who has the hub URL and this password can push, pull, and delete sessions.

### Pick a storage folder

Choose a folder on the hub machine that is **not** `~/.claude`. Session files are plain `.jsonl` files in that folder. Backup means copying the folder. If the disk fills up, delete old session files by hand.

### Python path

On the hub machine only, set the password with `export` (the hub does not read `.env`):

```bash
export WEAVE_HUB_PASSWORD=your-secret
weave-hub --dir /path/to/chats
```

Default listen address: `http://127.0.0.1:8080`. The default `--host 127.0.0.1` accepts connections from the same machine only. For two machines without Docker, bind on all interfaces:

```bash
export WEAVE_HUB_PASSWORD=your-secret
weave-hub --dir /path/to/chats --host 0.0.0.0 --port 8080
```

Teammates then use `http://<hub-computer-ip>:8080` as the remote URL.

The Python hub runs until you stop it. Leave that terminal open, or start it in tmux or screen so it keeps running after you disconnect.

The `weave` CLI autoloads a `.env` file (from the current directory, or from `WEAVE_ENV_FILE`). The hub process does not.

You can also run `python -m weave.hub --dir /path/to/chats`.

### Docker path

Copy `.env.example` to `.env` and set `WEAVE_HUB_PASSWORD`. Then:

```bash
docker compose up
```

Chats are stored in `./chats` on the host (bind mount to `/data` in the container). The hub listens on port 8080. `compose.yaml` sets `restart: unless-stopped`. If you want the hub up after a reboot, enable Docker Desktop to start on login (or your platform equivalent) on the machine that runs the hub. Inside the container the hub listens on `0.0.0.0`.

### Reachability

Demo on localhost is fine. For two machines, point teammates at the hub computer's URL (not `localhost`), and keep that computer awake.

## Password on every laptop that push/pulls

Every machine that runs `weave push` or `weave pull` needs the same `WEAVE_HUB_PASSWORD`. The CLI reads it from the environment or from a `.env` file in the current working directory:

```bash
export WEAVE_HUB_PASSWORD=your-secret
```

Or create `.env` in the project folder (the `weave` CLI loads this; the hub process does not):

```
WEAVE_HUB_PASSWORD=your-secret
```

## Point a project at the hub

`cd` to the project folder (the folder where you run Claude Code):

```bash
weave remote add origin http://localhost:8080
```

Use the real hub URL when the hub is on another machine, for example `http://192.168.1.10:8080`. The name `origin` is just a label, like git remotes.

This creates `.weave/config` in the current folder. Later, from `src/` or any subfolder, weave walks up the directory tree until it finds that config. Chats belong to the project folder where you ran `remote add`, not to a nested subdirectory.

Duplicate remote names are an error. Commit `.weave/config` so teammates get the hub URL from git. Ignore the operation log:

```gitignore
.weave/log
```

Example `.weave/config`:

```ini
[remote "origin"]
url = http://localhost:8080
```

## Engineer A pushes

Run Claude Code in that project folder first so a local session exists.

List local session ids (no remote argument):

```bash
weave ls
```

If there is exactly one local chat for the project, push it:

```bash
weave push origin auth-refactor
```

If there are several local sessions, pick one:

```bash
weave ls
weave push origin auth-refactor --session <id>
```

Session names may use letters, numbers, and hyphen. They are stored lowercase. Pushing the same name twice is an error. To push the same chat again under the same name, delete the old remote copy first (`weave rm origin auth-refactor`), then push. Or pick a new name.

Confirm on the hub:

```bash
weave ls origin
```

Remote `ls` prints names only, not full session ids.

## Engineer B continues

Engineer B gets the code through git as usual. Install weave on B's machine. Set the same `WEAVE_HUB_PASSWORD`. If `.weave/config` came from git, B is done. Otherwise run the same `weave remote add` command.

Pull the session and open it in Claude:

```bash
weave pull origin auth-refactor -o
```

Pull writes a **new** local session (new id). Weave rewrites `cwd` and `sessionId` on lines that carry them so Claude can open the chat on B's machine even when home directory paths differ. Other line types are kept. Pull does not merge into B's existing Claude chat; it creates a separate file.

If `claude` is not on PATH, weave prints `claude --resume <id>` instead of launching Claude. After a successful pull, weave prints the folder it wrote into and the resume command.

## What is in the file

Claude Code stores conversations as JSONL at:

```
~/.claude/projects/<encoded-path>/<uuid>.jsonl
```

If `CLAUDE_CONFIG_DIR` is set, use that directory instead of `~/.claude`.

The encoded path is derived from the project folder path: every character that is not alphanumeric becomes `-`. JSONL means one JSON object per line (user and assistant messages, thinking blocks, tool calls, metadata, and so on).

## Commands

| Command | Description |
| --- | --- |
| `weave remote add <name> <url>` | Register a hub URL. Creates `.weave/config` in the current folder. |
| `weave push [<remote>] <name> [--session <id>]` | Upload a local session. Omit `--session` when exactly one local chat exists; pass it when several do. |
| `weave pull [<remote>] <name> [-o]` | Download a named session into a new local file with `cwd` / `sessionId` rewritten. `-o` runs `claude --resume` when `claude` is on PATH. |
| `weave rm [<remote>] <name>` | Delete a session on the hub. Local files are not touched. |
| `weave ls [<remote>]` | List session names on a remote, or local session ids when no remote is given. |
| `weave log` | Show local history of push / pull / rm (newest first). |
| `weave help` | Command reference. |

When exactly one remote is configured, you can omit `<remote>` on push, pull, rm, and ls.

### weave-hub

| Flag | Description |
| --- | --- |
| `--dir <path>` | Folder to store chats (required; not `~/.claude`). |
| `--host <address>` | Bind address (default `127.0.0.1`). |
| `--port <port>` | Port (default `8080`). |

Requires `WEAVE_HUB_PASSWORD` in the environment.

## Troubleshooting

Weave prints errors to stderr with the prefix `weave: `.

| Message (after `weave: `) | What it means |
| --- | --- |
| `not a Weave project — run: weave remote add <name> <url>` | No `.weave/config` found walking up from the current directory. |
| `no remote configured — run: weave remote add <name> <url>` | Config exists but has no remotes. |
| `multiple remotes configured (...); specify one` | More than one remote; name the one you mean. |
| `no local Claude sessions for '...' — run Claude Code from that folder first` | No local chat for this project path. |
| `multiple local sessions for '...' (...); pass --session <id>` | Several local chats; pass `--session`. |
| `push ...: set WEAVE_HUB_PASSWORD` (or `pull` / `ls` / `rm`) | Password not in the environment or `.env`. |
| `...: bad password` | `WEAVE_HUB_PASSWORD` does not match the hub. |
| `...: hub unreachable at <url>` | Hub is down, wrong URL, or blocked by network/firewall. |
| `push ...: name '...' already exists` | That name is already on the hub. |
| `...: name must be letters, numbers, and hyphen` | Invalid session name. |
| `pull ...: no session '...' on remote` | No session with that name on the hub. |
| `'claude' not found on PATH; resume manually with: claude --resume <id>` | Pull succeeded; run the printed command yourself. |

Installer messages (not prefixed with `weave:`):

- `weave install supports macOS and Linux only`
- `Python 3.11+ required (found ...)`

## Limits

- No user accounts. One shared password for the whole hub.
- Anyone with the password can delete sessions with `weave rm`.
- Full transcripts live as files on the hub machine, including secrets you pasted into Claude.
- No merge, no fork, and no `weave resume`.
- `weave ls` on a remote prints session names only.
