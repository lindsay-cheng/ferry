<p align="center">
  <img src="assets/ferry.png" width="220" alt="Ferry">
</p>

<h1 align="center">Ferry</h1>

<p align="center">
  <em>Ferry moves your Claude Code session from one computer to another.</em>
</p>

---

Ferry preserves the exact agent state: thinking blocks, tool calls, attachments, and subagents, things that /compact erases.

## Install

```bash
brew install lindsay-cheng/tap/ferry
```

## Use

Computer A already used Claude Code in a project folder. The Claude Code session file lives on computer A. Computer B has the same project folder and does not have that session.

Install ferry on computer A and on computer B. On each computer, open a terminal, `cd` to the project folder, then type the commands below.

On computer A:

```
$ ferry export auth-refactor
/Users/jordan/api/auth-refactor.jsonl
```

This writes `auth-refactor.jsonl` in the current folder. On a Mac, ferry also copies the file to the clipboard. Send that file to a teammate on computer B by Slack, AirDrop, email, or USB.

If more than one Claude Code session exists for the working directory, ferry prints a numbered list. Session 1 is the most recently changed session. Press Enter to export session 1, or type another number.

```
$ ferry export auth-refactor
1. fix the login form
2. add the rate limiter
Choice [1]: 2
/Users/jordan/api/auth-refactor.jsonl
```

`ferry ls` prints the same list. `ferry export auth-refactor --session 2` selects that number without the prompt.

On computer B, the teammate downloads the file and imports it.

```
$ ferry import auth-refactor.jsonl
imported into 7c9e6679-7425-40de-944b-e07fc1f90ae7
  folder: /Users/sam/.claude/projects/-Users-sam-api
  resume: claude --resume 7c9e6679-7425-40de-944b-e07fc1f90ae7
```

This imports the file at that path. `ferry import` with no path lists `.jsonl` files in the current folder and in `~/Downloads`.

```
$ ferry import
1. /Users/sam/Downloads auth-refactor.jsonl
2. /Users/sam/api notes.jsonl
Choice [1]:
```

If more than one `.jsonl` file exists, ferry prints a numbered list. If only one file exists, ferry imports that file.

On computer B, open the session in Claude Code:

```
$ ferry import auth-refactor.jsonl -o
imported into 7c9e6679-7425-40de-944b-e07fc1f90ae7
  folder: /Users/sam/.claude/projects/-Users-sam-api
  resume: claude --resume 7c9e6679-7425-40de-944b-e07fc1f90ae7
```

`-o` runs `claude --resume` when `claude` is on PATH. If `claude` is not on PATH, ferry prints the resume command.

The export is the raw session. If computer A pasted a secret into Claude, it is in the file. Do not commit it.

## Commands


| Command                                | Description                                                                            |
| -------------------------------------- | -------------------------------------------------------------------------------------- |
| `ferry export <name> [--session <number>]` | Write a local session to `<name>.jsonl` in the current folder.                         |
| `ferry import [<file>] [-o]`               | Import a `.jsonl` file into a new local session. `-o` opens it with `claude --resume`. |
| `ferry ls`                                 | List local sessions as a numbered list. Session 1 is the most recently changed.        |
| `ferry help`                           | Command reference.                                                                     |
| `ferry --version`                      | Print the installed version.                                                           |


Export names use letters, numbers, and hyphen. Ferry stores names in lowercase.

Ferry began as "Weave" at a hackathon made by Alex Tan, Raiyan Haque, Sujal Thapa, and Lindsay Cheng.

## License

[MIT](LICENSE)
