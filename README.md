# ferry

Ferry copies a Claude Code chat as a `.jsonl` file from one computer to another. Git still moves the source code. Ferry packs and unpacks the conversation file. Ferry is not a merge tool, not a fork tool, and there is no `ferry resume`. Ferry is a single Go binary. You do not need Python to run ferry.

If you already have a `.weave` folder from an older install, rename it to `.ferry` (same contents; ferry does not auto-migrate).

## What you need

- Claude Code already installed and used in the project you want to share.
- macOS or Linux.
- `git` on your PATH (the curl installer clones from GitHub).
- Go 1.22 or newer (only if you build from source; the curl installer checks for Go).

## Install

**Mac with Homebrew** (once this repo is public and the tap is available):

```bash
brew tap lindsay-cheng/ferry https://github.com/lindsay-cheng/ferry
brew install ferry
```

Homebrew needs a public GitHub repo and a git tag for a stable install without `--HEAD`. Until then, use curl, `./install.sh`, or `go build` from a clone.

**Curl** (Mac and Linux, no sudo):

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/ferry/main/install.sh | bash
```

`install.sh` is a small bash script in this repository. The curl command downloads it and runs it in your shell. The script refuses Windows. It checks that Go 1.22+ and `git` are available. It builds the Go binary and installs it to `~/.local/bin/ferry`. If `~/.local/bin` is not on PATH, the script prints a hint.

While this repository is private, the raw GitHub URL for `install.sh` returns 404 unless the repo is public or you host the script elsewhere. If curl fails with 404, clone the repo with your normal GitHub access and run `./install.sh` from the repo root.

Checks only (no install):

```bash
curl -fsSL https://raw.githubusercontent.com/lindsay-cheng/ferry/main/install.sh | bash -s -- --check
```

**Build from a clone** (if you already have the repo):

```bash
git clone https://github.com/lindsay-cheng/ferry.git
cd ferry
go build -o ~/.local/bin/ferry ./cmd/ferry
```

Or run `./install.sh` from the repo root. It detects `go.mod` and `cmd/ferry` and builds in place.

Verify:

```bash
ferry help
ferry --version
```

If `ferry` is not found, add `~/.local/bin` to PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### Upgrade

Re-run the curl installer, or rebuild from a fresh clone with `go build -o ~/.local/bin/ferry ./cmd/ferry`.

For Homebrew after a public tag exists: `brew upgrade ferry`.

## Move a chat with a file

This path needs no hub, no password, and no `.ferry/config`.

### Export on computer A

Run Claude Code in the project folder first so a local session exists.

```bash
ferry export auth-refactor
```

This writes `auth-refactor.jsonl` in the current folder. Session names may use letters, numbers, and hyphen. They are stored lowercase. If the name already ends in `.jsonl`, ferry does not add `.jsonl` again.

Session pick: if exactly one local chat exists for the project, ferry uses it. If several exist, pass `--session`:

```bash
ferry ls
ferry export auth-refactor --session <id>
```

Chat folder for export: ferry walks up the directory tree for a `.ferry` **directory**. If `.ferry` exists, chats belong to that project root. If `.ferry` does not exist, ferry uses the current folder.

On Mac, after the write, ferry copies the file onto the clipboard as a file (not as text). A paste in the Slack desktop app attaches the file. If the copy fails, the jsonl still exists and ferry prints the path. On Linux, ferry writes the file only.

Send the file by Slack, AirDrop, email, or USB. Ferry does not upload it.

### Import on computer B

```bash
ferry import auth-refactor.jsonl
```

Or omit the path to pick from `*.jsonl` files in the current folder and in `~/Downloads` (newest first). One file: ferry uses it with no prompt. Two or more: ferry prints a numbered list and waits. Return takes item 1. A number picks that item. Zero files: ferry prints usage.

Open the chat in Claude after import:

```bash
ferry import auth-refactor.jsonl -o
```

`-o` runs `claude --resume` when `claude` is on PATH. If `claude` is missing, ferry prints the resume command.

Import writes a **new** local session (new id). Ferry rewrites `cwd` and `sessionId` on lines that carry them so Claude can open the chat on B's machine even when home directory paths differ. Other line types are kept. Import does not merge into an existing Claude chat.

After import, ferry prints the folder it wrote into and the resume command.

### Secrets

The jsonl is the raw chat, including secrets pasted into Claude. Do not commit the export. Do not treat the attached file as safe to share with the world.

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
| `ferry export <name> [--session <id>]` | Write a local session to `<name>.jsonl` in the current folder. |
| `ferry import [<file>] [-o]` | Import a `.jsonl` file into a new local session. `-o` runs `claude --resume` when `claude` is on PATH. |
| `ferry ls` | List local session ids for the current project. |
| `ferry help` | Command reference. |
| `ferry --version` | Print the installed version. |

## Troubleshooting

Ferry prints errors to stderr with the prefix `ferry: `.

| Message (after `ferry: `) | What it means |
| --- | --- |
| `file not found: ...` | Import path does not exist. |
| `no .jsonl file in current folder or Downloads — pass a path` | Import with no path and no jsonl in cwd or Downloads. |
| `multiple .jsonl files — pass a path or a number` | Import with no path, several files, and stdin is not a TTY. |
| `invalid choice: ...` | Import list prompt got a bad number or text. |
| `auth-refactor.jsonl already exists` | Export name already exists in the current folder. |
| `name must be letters, numbers, and hyphen` | Invalid export or session name. |
| `file has no chat history` | Import file is empty or has no valid chat lines. |
| `no local Claude sessions for '...' — run Claude Code from that folder first` | No local chat for this project path. |
| `multiple local sessions for '...' (...); pass --session <id>` | Several local chats; pass `--session`. |
| `'claude' not found on PATH; resume manually with: claude --resume <id>` | Import succeeded; run the printed command yourself. |

Installer messages (not prefixed with `ferry:`):

- `ferry install supports macOS and Linux only`
- `go not found; install Go 1.22+ from https://go.dev/dl/`
- `Go 1.22+ required (found ...)`
- `clone failed; if the repo is private, clone it with your GitHub access and run ./install.sh from the repo root`

## Limits

- Ferry moves chats as files only. There is no hub and no remote server.
- No user accounts.
- Full transcripts live in exported jsonl, including secrets you pasted into Claude.
- No merge, no fork, and no `ferry resume`.
