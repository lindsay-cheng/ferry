# Changelog

## 0.1.0

- CLI: export, import, push, pull, rm, remote add, ls, log
- `export` writes a named `.jsonl` in the current folder; `import` reads one into a new local session
- HTTP file hub (`ferry-hub`) with shared env password (optional)
- Pull and import rewrite `cwd` / `sessionId` into a new local Claude jsonl
- Homebrew formula (`Formula/ferry.rb`) for Mac install via tap
