# weave

> Git primitives for Claude Code sessions.

Weave makes Claude Code sessions first-class citizens of your team's workflow. Pull a colleague's session and resume it on your machine with exactly the context they had — same thinking blocks, same tool results, same reasoning chain — as if the session had been running on your computer all along. Fork a session to explore a different approach without losing the original. Merge two sessions into one when parallel work needs to come together. Push sessions to a shared remote your whole team can pull from. With weave users don't have to waste time setting up their coding agent and transfering data/intent, instead it's as if they picked off right where the last person stopped

The name is `weave merge` but the primitive is broader: Claude Code sessions should travel across machines and engineers as naturally as git commits do.

---

## Install

Requires Python 3.11+ and [pipx](https://pipx.pypa.io/).

```bash
brew install pipx    # one-time
pipx ensurepath      # one-time

git clone https://github.com/alexploopy/weave.git
cd weave
pipx install -e ".[dev]"
```

Verify:

```bash
weave --help
weave --version    # prints the installed version (also: weave -V)
```

### Set up Supabase

Weave stores sessions in Supabase. Create a project, then run the migration in
`[supabase/migrations/0001_init_weave_sessions.sql](supabase/migrations/0001_init_weave_sessions.sql)`
in the Supabase SQL editor.

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
```

Set `SUPABASE_URL` and `SUPABASE_KEY` (service-role key). Set `CEREBRAS_API_KEY` if you want `weave merge`.

### Add a remote

```bash
weave remote add origin weave://my-team
```

This writes `.weave/config`. Commit it so your team gets the remote automatically.

---

## The problem

Claude Code sessions are trapped on the machine that created them. When two developers work on separate problems, their conversational context lives in two separate JSONL files on separate machines. You cannot hand that context to a colleague without sending a raw transcript they have to read, understand, and re-explain to their own Claude session. You cannot pick up where a teammate left off. You cannot split a session into two parallel explorations. You cannot carry another engineer's full reasoning — thinking blocks, failed attempts, tool results — onto your own machine and just keep going.

---

## The solution

Claude Code stores conversations as JSONL at `~/.claude/projects/<encoded-path>/<uuid>.jsonl`, including thinking blocks and tool results. Weave treats this history as a first-class primitive — the same way git treats commits — and gives you the operations that should have always existed:

- **Handoff** — pull a colleague's session onto your machine and resume it exactly as they left it. Claude already has their full context: what was tried, what failed, what was decided, and why.
- **Fork** — split your current session into two independent copies. Explore a different approach in one without touching the other. If it works, push it. If it doesn't, your original is untouched.
- **Merge** — combine two sessions into one. Cerebras runs locally, reads both conversation histories, and produces a unified session that preserves reasoning from both sides, deduplicates redundant tool calls, and flags where the two lines of work conflict.

---

## Merge pipeline

```
weave merge <session-a> <session-b>

  ┌─ Parse ────┐  ┌─ Distill ──┐  ┌─ Merge ────┐  ┌─ Write ───┐
  │ JSONL →    │  │ ChatContext│  │ Cerebras   │  │ merged    │
  │ typed      │→ │ signal not │→ │ unifies    │→ │ JSONL to  │
  │ records    │  │ raw noise  │  │ both sides │  │ ~/.claude │
  └────────────┘  └────────────┘  └────────────┘  └───────────┘
                                                        ↓
                                             reprompt loop if rejected
```

### Stages


| Stage             | Description                                                                                                                                                                                                                                                                                                                                                                      |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Parse**         | Reads JSONL files into typed records (`user`, `assistant`, thinking blocks, `tool_use`, `tool_result`) and ignores the rest.                                                                                                                                                                                                                                                     |
| **Distill**       | Normalizes sessions into a `ChatContext` capturing intent, assistant decisions, thinking blocks, tool interactions, failures, and unresolved points.                                                                                                                                                                                                                             |
| **Merge**         | Prompts Cerebras with both distilled contexts to return a unified conversation thread that preserves reasoning, deduplicates tool calls, and flags conflicts.                                                                                                                                                                                                                    |
| **Write**         | Places the merged JSONL in `~/.claude/projects/<cwd>/` with corrected `cwd` fields. Every record's `cwd` field is rewritten from the source engineer's encoded path (e.g. `-Users-alice-myapp`) to the local machine's encoded path (e.g. `-Users-bob-myapp`). Without this rewrite, `claude --resume` silently starts a fresh session instead of picking up the merged context. |
| **Reprompt loop** | Re-runs failed or rejected merges using feedback, passing the prior attempt and feedback back to Cerebras.                                                                                                                                                                                                                                                                       |


---

## WeaveHub

Weave uses a remote directory over SSH to share sessions between engineers, mirroring how git uses remotes. No custom server software is required — just a directory on any Linux machine or VPS your team controls.

```bash
# Set up a WeaveHub once on any machine with SSH
mkdir -p /srv/weave/myteam
```

Configure the remote in your project via `.weave/config` and commit it to the repo. Every team member who clones the repo gets the WeaveHub config automatically.

```ini
[remote "origin"]
    url = user@mycompany.com:/srv/weave/myteam
```

New team members point their local machine at the WeaveHub with:

```bash
weave remote add origin user@mycompany.com:/srv/weave/myteam
```

Session names are scoped to the remote, so `auth-refactor` on one team's WeaveHub never collides with another team's.

### Commands


| Command                                  | Description                                                                                                                                                                                           |
| ---------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `weave remote add <name> <url>`          | Register a WeaveHub remote (mirrors `git remote add`).                                                                                                                                               |
| `weave push origin <name> [--session <id>]` | Upload a local session to the WeaveHub. Defaults to your newest local session; pass `--session <id>` to choose another.                                                                          |
| `weave pull origin <name> [-o]`          | Download a named session from the WeaveHub and place it locally, rewriting `cwd` fields for your machine. Resume immediately with `claude --resume`, or pass `-o` / `--open` to resume automatically. |
| `weave fork <name>`                      | Split your current session into two independent local copies. The original is preserved; the fork is yours to diverge.                                                                               |
| `weave merge <source-a> <source-b> [-o]` | Merge two sessions into a new resumable session via Cerebras. Pass `-o` / `--open` to resume the merged session automatically.                                                                        |
| `weave resume`                           | Shortcut for `weave pull` + `claude --resume` in one step.                                                                                                                                           |
| `weave ls origin`                        | List available sessions on the WeaveHub.                                                                                                                                                             |
| `weave show <name>`                      | Preview the distilled context for a session.                                                                                                                                                         |

> **Note:** `weave merge` automatically snapshots your current session to the WeaveHub before making local changes. If the merge fails, your original session is untouched and recoverable.

### Typical flows

**Handoff** — pick up where a teammate left off:

```bash
# Engineer A pushes their session
weave push origin auth-refactor

# Engineer B pulls it and resumes as if it ran on their machine
weave pull origin auth-refactor -o    # -o / --open resumes automatically
```

**Fork** — explore a different approach without losing the original:

```bash
# Fork your current session into two independent copies
weave fork my-current-work

# One copy stays as-is, the other is yours to take in a new direction
# Push whichever works out
weave push origin my-current-work
```

**Merge** — combine two sessions into one:

```bash
# Engineer A finishes and shares their session
weave push origin auth-refactor

# Engineer B pulls and merges A's context into their own session
weave pull origin auth-refactor
weave merge auth-refactor my-current-work -o   # -o / --open resumes the merged session
```

### Multiple sessions in the same directory

If you have more than one active Claude Code session running from the same project directory, specify the target session explicitly:

```bash
weave merge auth-refactor --into <session-id>
```

Run `weave ls` (no remote) to list local sessions and their IDs.

---

## Architecture

All runtime code lives under the `weave/` package. Each module is a directory
with an `__init__.py` defining its public surface over private implementation
files, and each is independently testable.


| Module             | Responsibility                                                                                              | Depends on      |
| ------------------ | ----------------------------------------------------------------------------------------------------------- | --------------- |
| `weave.cli`        | Argument parsing and CLI marshalling.                                                                       | `weave.core`    |
| `weave.core`       | Orchestrates push/pull/fork/merge; owns all machine-specific policy (id choice, cwd/sessionId rewrite).     | all             |
| `weave.connector`  | Local-filesystem byte I/O: session id ↔ `~/.claude` JSONL path.                                             | —               |
| `weave.transcript` | Linear CRUD over a transcript's active branch (`api`) over a private linearize/serialize engine (`engine`). | —               |
| `weave.remote`     | Supabase-backed byte transport (`push` / `pull` / `list`), keyed by `(url, name)`.                          | —               |
| `weave.config`     | Resolves `.weave/config` remotes.                                                                           | —               |
| `weave.context`    | Parses Claude JSONL into a `ChatContext` and distills it.                                                   | —               |
| `weave.merge`      | Cerebras client, prompt building, response parsing, and validation.                                         | `weave.context` |


### Project layout

```
weave/         # all runtime code (one package per module)
tests/         # every test, shared helpers, and JSONL/JSON fixtures
docs/          # design specs and plans
supabase/      # remote-transport schema migrations
```

---

## Error handling


| Case                              | Behavior                                                                                                                                                               |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Unparseable model output          | Surfaces the raw output for inspection instead of writing a broken JSONL file. If the user rejects a merge result, re-runs with that feedback passed back to Cerebras. |
| No chat history                   | Warns the user and exits before modifying files.                                                                                                                       |
| Cerebras unreachable / no API key | Throws a clear error and exits before touching the local session.                                                                                                      |
| Merge failure                     | Local session remains untouched; original state is recoverable via the WeaveHub snapshot.                                                                              |


---

## Testing & demo strategy

The plumbing is genuinely end-to-end (real JSONL, real Cerebras), but the demo runs on seeded fixtures for deterministic results.

- **Fixtures** — two seeded JSONL histories committed in-tree representing different solutions to the same problem.
- **Unit tests** — golden tests on JSONL parsing and context distillation; `merge` tested against a mocked Cerebras response.
- **Integration tests** — one real-Cerebras test gated behind the `CEREBRAS_API_KEY` environment variable.

---

## Configuration


| Variable           | Purpose                                                        |
| ------------------ | -------------------------------------------------------------- |
| `CEREBRAS_API_KEY` | Authentication for Cerebras inference (OpenAI-compatible API). |


---

## Status

Proof of concept — hackathon build. Implemented in Python.
