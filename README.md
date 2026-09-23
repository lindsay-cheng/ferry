<p align="center">
  <img src="assets/ferry.png" width="220" alt="Ferry">
</p>

<h1 align="center">Ferry</h1>

<p align="center">
  <em>Ferry moves your Claude Code session from one computer to another.</em>
</p>

---

Ferry preserves the exact agent state: thinking blocks, tool calls, attachments, and subagents, things that /compact erases.

Ferry began as Weave at a hackathon with Alex Tan, Raiyan Haque, Sujal Thapa, and Lindsay Cheng.

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

If more than one Claude Code session exists for the working directory, ferry prints a numbered list. Session 1 is the most recently changed session. Press Enter to export session 1, or type another number:

```
$ ferry export auth-refactor
1. fix the login form
2. add the rate limiter
Choice [1]: 2
/Users/jordan/api/auth-refactor.jsonl
```

`ferry ls` prints the same list. `ferry export auth-refactor --session 2` selects that number without the prompt.

On computer B, the teammate downloads the file, then imports and opens it:

```
$ ferry import auth-refactor.jsonl -o
imported
  folder: /Users/sam/.claude/projects/-Users-sam-api
```

`-o` runs `claude --resume` when `claude` is on PATH. If `claude` is not on PATH, ferry prints the resume command.

If more than one `.jsonl` file exists in the current folder or in `~/Downloads`, ferry prints a numbered list. File 1 is the most recently changed file. Press Enter to import file 1, or type another number:

```
$ ferry import
1. /Users/sam/Downloads auth-refactor.jsonl
2. /Users/sam/api notes.jsonl
Choice [1]:
```

`ferry import` with no path uses that list. Add `-o` to open after import. If only one `.jsonl` file exists, ferry imports that file with no prompt.

Without `-o`, ferry prints the `claude --resume` command instead of opening the session.

The export is the raw session. If computer A pasted a secret into Claude, it is in the file. Do not commit it.

## Commands


| Command                                    | Description                                                                            |
| ------------------------------------------ | -------------------------------------------------------------------------------------- |
| `ferry export <name> [--session <number>]` | Write a local session to `<name>.jsonl` in the current folder.                         |
| `ferry import [<file>] [-o]`               | Import a `.jsonl` file into a new local session. `-o` opens it with `claude --resume`. |
| `ferry ls`                                 | List local sessions as a numbered list. Session 1 is the most recently changed.        |
| `ferry help`                               | Command reference.                                                                     |
| `ferry --version`                          | Print the installed version.                                                           |


Export names use letters, numbers, and hyphen. Ferry stores names in lowercase.

## License

[MIT](LICENSE)