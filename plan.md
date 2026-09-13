# Weave — plan

Hackathon code lives in WEAVE-HACKATHON. This folder is the real project. Port the source here and put it on GitHub under my profile.

Goal before the 8090 intern interview (early November): easy to install, easy to use, Claude Code only. Core loop works with no Cerebras account and no Supabase. Share sessions like git: local first, optional remote. Teams can run their own hub or use one I host.

---

## Install

Today it is a folder of Python files. `pyproject.toml` already says: the command `weave` runs `weave.cli:main`. `pipx install` (or `curl | bash` that does the same) copies that package into a hidden folder on the machine and puts `weave` on PATH. The logic still lives in those Python files — just installed like git, not sitting in their app repo. Their project only gets `.weave/config`.

Wanted: one command, `curl | bash` style (download + install, not clone the repo).

A landing page with some text and that install command is enough. Vercel (or similar) is fine for that page. Do not use Docker or AWS just to host a static page.

---

## Local vs hub

The CLI runs on each person's laptop. It has to see Claude's chats on that machine (`~/.claude/...`), so do not put the CLI in Docker.

The hub is one computer that stays on. People `weave push` / `weave pull` against it. Sessions are files in a folder on that computer. Not a database. Docker's job is only: run the hub program, and do not throw that folder away when the program restarts.

Laptops sleep and change wifi. The hub is not everyone's laptop. It is a cheap always-on box, a spare company server, or (later) a machine I run.

SSH (what the hackathon README mentioned): a way to log into another computer over the network. Git uses it to talk to GitHub. The old WeaveHub idea was "a folder on a machine you can SSH into" — copy session files there, no Docker, no AWS, no extra program. Fine as a later remote type. People do not need to learn SSH for v1. Docker hub is the easier path and the Docker resume line.

Backup = copy that folder. Update = restart the hub program. Disk fills up = delete old named sessions. No auto-delete / TTL. Git does not expire old commits and we should not expire old chats.

---

## Docker / the hub computer

Docker is appropriate for the hub, not the CLI.

The "short start file" is only for the hub: a small recipe that says start the Weave hub, save chats in this folder, password is X. Copy it onto the always-on computer, set a password, one start command. Teammates never touch this.

That program should take sessions, keep them, and hand them back. It should not merge.

If there is no hub program, Docker is fake and should not go on the resume. AWS CDK only makes sense if I actually host the hub on AWS. Otherwise skip it.

Setup for a team, start to finish:
1. Pick an always-on computer, note its address
2. Install Docker there once
3. Put the start file on it, set a password, start it
4. Each person installs the CLI on their laptop
5. In each git repo, once: `weave remote add origin <hub-address>` and commit that
6. Daily: push / pull from laptops. The hub just sits there

---

## Config / which folder you are in

`.weave/config` is not created by install. It appears when someone runs `weave remote add` inside a repo, then they commit it. Same idea as git remotes.

The `weave` command is global. Which chats and which hub follow the folder you are in.

Today Weave only looks in the current folder. Git walks up (this folder, then parent, then parent...) until it finds `.git`. If it never finds one it errors: not a git repository. Weave should walk up for `.weave/config` and if none exists, say this folder is not a Weave project. Right now even `repo/src/` can miss the config. Wrong folder today often looks like "no remote configured" which is a bad message.

One hub for the team is enough. Many repos can point at the same hub. "Once per project" means each repo records the hub address, not one hub per repo.

Two hubs in one project is fine (origin, backup). If both exist you have to say which one. Two remotes with the same name: the second add overwrites the first.

---

## Names

People type short names when they push: `auth-refactor`. Not the random ids Claude uses on disk.

Same name on the same hub overwrites. No confirm today.

At small scale, names are enough. At scale, two repos will both push `auth-refactor` and clobber each other. Fix behind the scenes: keep a separate bucket per project. People still type the short name. Show which project on `ls`. Do not put the project into the name they type.

Rules we want: letters, numbers, hyphen. No empty names, no `/`, no `.` or `..`. Spaces only if quoted; better to disallow.

These rules are not given to users today. Nothing checks them. No error if you use a slash or a weird name. `weave ls` is just a list of names/ids, no date, who pushed, which project, or size. Those belong on `ls` as extra info, not inside the name.

---

## What a session file looks like

A Claude chat is a `.jsonl` file: one JSON object per line, on disk under `~/.claude/projects/<folder-name>/<random-id>.jsonl`. Real files are hundreds of KB; one line (a fat tool result) can be tens of thousands of characters.

Each chat line is linked to the previous one with ids (`uuid` / `parentUuid`), like a chain. If you rewind in Claude, the file grows a fork: old messages stay, new ones branch off. Claude resumes the branch that ends at the last line.

Not every line is a message. Real files also have bookkeeping: mode, permission mode, titles, file-history snapshots, attachments, system lines. There is often a sibling folder with the same id that holds subagent chats. Those extra files are not in the main jsonl.

It is a normal text file. Weave already edits it: on pull it rewrites folder path and session id, rebuilds the parent links into one chain, and drops lines with no uuid (titles, snapshots, etc.). So yes, it is modifiable. The risk is writing something Claude will not resume, or dropping bookkeeping Claude still wants (undo snapshots, subagents). Blindly concatenating two files breaks the chain. Parsing and rewriting links can keep it valid.

The session is the conversation, not the repo. Pulling a chat does not check out their git branch or copy their files. Claude may think a file looks like it did on the other machine.

---

## Merging

Not decided. Merge is not in v1 unless we pick an option below. It should stay on the laptop, never the hub.

Today's code uses Cerebras to write a summary and throws away the real extra messages. That is the opposite of "hand off the full chat." Drop it as a requirement.

What if we just chain two chats (A then B, rewrite the links so it looks like one sitting)?
- The file can be valid. Claude will resume it.
- If B actually continued A's work, it can feel right.
- If they worked in parallel (two different fixes), Claude sees both stories as one timeline and can get confused.
- Chaining is not magic merge. It is concatenation with the paperwork fixed.

Options (pick later):
1. No merge command. Push/pull only. If you need both chats, pull both and pick one. Recommended for v1.
2. Chain: stitch B onto the end of A, keep everything, new file, do not delete originals. Honest about "this is A then B."
3. Keep the AI summary (Cerebras). Easier to read, loses the real chat. Against the product.
4. No weave merge: pull the other session and let the human paste or tell Claude to read it.

Goal of the app is handoff, not git-merge. Option 1 matches that.

---

## Edge cases (agree / disagree on each fix)

Some mistakes already print `weave: ...`. Aim: one short sentence, never a Python crash dump.

You ran the command from the wrong folder
Weave looks in this folder only, so it may say "no remote" even if the repo is one level up.
Fix: search parent folders for `.weave/config` (like git). If none, say "this is not a Weave project."

You are inside `repo/src/`
Same as above. Git handles this; we do not.
Fix: same walk-up.

Two different folders look like the same Claude project
Claude turns `/Users/you/app` into a folder name with dashes. A shortcut and a real path can collide.
Fix: always use the real path. If two chats share an id, refuse and name both folders instead of picking one.

Claude's files are not in the default `~/.claude`
People can point Claude at another directory.
Fix: respect that setting (`CLAUDE_CONFIG_DIR`), same as Claude.

Password ends up in git
Someone puts the hub password in `.weave/config` and commits it. Or commits `.weave/log`.
Fix: keep secrets out of config. Put password in env or a local file that git ignores. Add `.weave/log` to gitignore.

`weave remote add origin ...` a second time
Today it quietly overwrites the old address.
Fix: error unless they pass a flag like `--force`.

Bad session names (`/`, empty, spaces, `Auth` vs `auth`)
Nothing checks. Spaces look like extra command words.
Fix: only letters, numbers, hyphen. Lowercase. Clear error. Show the rules in `weave help`.

Two remotes, they do not say which
Already errors. Keep that.

`weave ls` is a bare list of ids/names
Hard to tell who pushed, when, how big, which project.
Fix: print name, date, who, size. Project too if one hub serves many repos.

No chats in this folder yet
Push fails in a vague way.
Fix: "no Claude sessions in this folder. Run Claude here first."

Several chats, push grabs the newest file
"Newest" is last saved, not "the one I mean."
Fix: if more than one, list them and require `--session` (or a name). Do not guess.

Claude is still writing while you push
Last line of the file can be cut in half.
Fix: skip a trailing broken line and warn, or refuse if the file was just modified.

Push misses extra Claude files
Subagent chats live in a sibling folder. Titles/snapshots are extra lines. Pull today drops some of that.
Fix: v1 copy the main chat file only, and say so. Do not claim subagents come along. On pull, keep unknown line types instead of dropping them.

Push to a name that already exists
Last push wins. No warning. Coworker can wipe your chat.
Fix: refuse unless `--force`. Later: warn if the hub copy is newer than what you last pulled.

Pull a name that is not on the hub
Should already fail.
Fix: "no session named X on origin."

Hub is down / wrong address / bad password
Can dump a stack trace.
Fix: one line: cannot reach the hub, or bad password.

Hub disk is full
Ugly crash.
Fix: "hub is out of disk space."

Chat is huge
Resume may blow Claude's context limit.
Fix: still allow it. On `ls`, show size. Warn if huge.

You pull while standing in the wrong repo
The chat gets attached to that folder.
Fix: walk-up config so "wrong repo" is rarer. Print where it was saved.

Two git repos, one hub, both push `auth-refactor`
They overwrite each other.
Fix: behind the scenes, store under project name + session name. People still type `auth-refactor`.

Hub password is shared
Anyone with the address and password can read chats. Chats may contain keys from terminal output.
Fix: v1: shared password is ok if we say "this is as private as your password." Do not log passwords. Later: per-user tokens.

`weave pull -o` but Claude is not installed
Fix: "pulled, but `claude` was not found. Install Claude Code, then: claude --resume <id>"

Resume opens a blank chat
Usually the folder path or session id in the file does not match this machine.
Fix: on pull, always rewrite those to this computer (already the idea). Add a test that resume is not empty.

Their files / git branch are not on your machine
The chat remembers file contents from their laptop. Your disk can differ.
Fix: this is inherent. Document it. Do not try to copy their whole repo.

They have a newer Claude than you
New line types we do not understand.
Fix: pass unknown lines through. Do not crash.

Their permission mode (e.g. skip checks) comes with the chat
Fix: strip permission/mode lines on pull, or warn. Default: warn.

Install: no Python, or too old
Fix: installer checks Python 3.11+ and says how to install. Or ship a binary later.

`weave` not found after install
PATH not updated until a new terminal.
Fix: installer prints "open a new terminal" and the full path to `weave`.

Mac vs Linux vs Windows
Fix: v1 Mac + Linux. Windows: "not supported yet" instead of a crash.

Hub computer reboots, Docker does not start
Fix: in the hub readme, say how to make Docker start on boot. Not a CLI problem.

Two people each run a hub, both call it origin
That is two different remotes that happen to share a nickname. Fine if each team's config has their address.
Fix: none. The address in `.weave/config` is what matters.

Merge-only (if we add merge later)
No shared history / identical chats / broken file / two conflicting stories.
Fix: skip merge in v1. If we chain later: refuse identical; if no overlap, still chain but print "these chats do not share a start."

---

## Landing page / AWS / resume keywords

Landing page + install command: simple static host. Vercel (or similar) is enough. Do not use AWS just for that page.

If everything is local — CLI on laptops, hub on a team box with Docker — there is no AWS to run. No login API, no database, no merge server.

Organic AWS only appears if something actually lives in Amazon's cloud.

"I host the hub" meant: my AWS runs the same Docker program 24/7, people point Weave at my address. That is a computer I pay for even when nobody uses it. For this project that is cost for almost no reason. Skip it unless I want a public demo badly enough to pay for it.

A bucket is different: you pay for stored files, not a machine sitting on. Still, if the bucket is on MY AWS, I am the host (cost + people sending me their chats). That is "renting them a folder," which is a real product later, not v1.

An S3 bucket is Amazon's folder in the cloud. Not a database. Not Supabase (Supabase is a hosted database + API; that is what the hackathon used). A bucket just holds files. Google and others have the same idea under different names. Supporting every cloud is extra work. v1 default should not lock people to AWS: Docker hub (or later SSH folder) works on any box. A bucket is an optional extra for teams already on AWS, not the only remote. If they use another cloud, they run the hub themselves.

Do not invent extra backend (users, billing, extra APIs) just to use AWS. Do not run a 24/7 hub just to have CDK on the resume.

Resume story: Docker = self-host hub. AWS/CDK = recipe for a team bucket (and only a hosted hub if I actually run one). Landing page stays boring.

If we skip cloud remotes, skip AWS. Do not put it on the resume.

---

## Porting

Hackathon source is copied here (not `.env`). GitHub: https://github.com/lindsay-cheng/weave (private). Next: local-first without Supabase/Cerebras, walk-up config, name rules + errors, Docker hub, curl install, simple landing page. Skip AWS for v1.
