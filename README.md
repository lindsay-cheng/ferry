![Ferry](assets/ferry.png)

# Ferry

*Ferry moves your Claude Code session from one computer to another.*

Ferry preserves the exact agent state: thinking blocks, tool calls, attachments, and subagents, things /compact erases.

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

This writes `auth-refactor.jsonl` in the current folder. On a Mac, ferry also copies the a reference of the file to the clipboard (i.e. the actual file itself, not just the text). Paste / attach the file via Slack, AirDrop, email, USB, etc. to a teammate on computer B.

If more than one local Claude Code session file exists in the cwd:

```
$ ferry ls
a1b2c3d4-e5f6-7890-abcd-ef1234567890
f0e1d2c3-b4a5-6789-0abc-def123456789
$ ferry export auth-refactor --session a1b2c3d4-e5f6-7890-abcd-ef1234567890
/Users/jordan/api/auth-refactor.jsonl
```

Then, on computer B, teammate downloads the sent file and imports and resumes a Claude Code session with preserved agent state.

```
$ ferry import auth-refactor.jsonl
imported into 7c9e6679-7425-40de-944b-e07fc1f90ae7
  folder: /Users/sam/.claude/projects/-Users-sam-api
  resume: claude --resume 7c9e6679-7425-40de-944b-e07fc1f90ae7
```

This imports the file at that path. Or, run `ferry import` with no path which lists `.jsonl` files in the current folder and in `~/Downloads` by name.

```
$ ferry import
1. /Users/sam/Downloads auth-refactor.jsonl
2. /Users/sam/api notes.jsonl
Choice [1]:
```

If more than one `.jsonl` file exists, a numbered list is printed with the name. Otherwise, ferry takes the only one available.

Finally, computer B, open the session in Claude Code:

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
| `ferry export <name> [--session <id>]` | Write a local session to `<name>.jsonl` in the current folder.                         |
| `ferry import [<file>] [-o]`           | Import a `.jsonl` file into a new local session. `-o` opens it with `claude --resume`. |
| `ferry ls`                             | List local session ids for the current project.                                        |
| `ferry help`                           | Command reference.                                                                     |
| `ferry --version`                      | Print the installed version.                                                           |


Export names use letters, numbers, and hyphen. Ferry stores names in lowercase.

## License

Ferry started as Weave at a hackathon with Alex Tan, Raiyan Haque, and Sujal Thapa.

[MIT](LICENSE)
