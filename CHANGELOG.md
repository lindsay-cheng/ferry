# Changelog

## 0.1.0

- Go CLI: `export`, `import`, `ls`, `help`, `--version`
- `export` writes a named `.jsonl` in the current folder; `import` reads one into a new local session
- Import rewrites `cwd` and `sessionId` into a new local Claude jsonl
- Hub removed (`push`, `pull`, `ferry-hub`, Docker)
- Homebrew formula builds the Go binary (`Formula/ferry.rb`)
