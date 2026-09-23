# Changelog

## 0.1.1

- `ferry ls` and `ferry export` print a numbered session list. Session 1 is the newest.
- `--session` accepts a list number. Enter selects session 1.
- `main.go` lives in `cmd/`.
- README uses the centered boat image and the Computer A / Computer B handoff.

## 0.1.0

- Go CLI: `export`, `import`, `ls`, `help`, `--version`
- `export` writes a named `.jsonl` in the current folder; `import` reads one into a new local session
- Import rewrites `cwd` and `sessionId` into a new local Claude jsonl
- Hub removed (`push`, `pull`, `ferry-hub`, Docker)
- Homebrew formula lives in the lindsay-cheng/homebrew-tap repository
