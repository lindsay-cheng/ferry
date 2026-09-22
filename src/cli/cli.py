"""argparse CLI for ferry: push / pull / remote add / ls.

Thin marshalling over ferry.core.

The top-level ``ferry help`` / ``ferry --help`` output is hand-rendered in a
git-like style (grouped commands, aligned parameter signatures, optional
arguments shown in [brackets]). Per-command help (``ferry <command> -h``) is
argparse's, tuned with ``<placeholder>`` metavars so optional positionals show
up bracketed there too.
"""

import argparse
import subprocess
import sys

from ferry import __version__, config, connector as cc, core

_TAGLINE = "git for your Claude Code agent context"

_FERRY_ART = (
    "\033[33m"
    "*%%*\n"
    "                    =**+  %@%%\n"
    "                    #@@%  %@@%\n"
    "               :%%%=#@%%=%%%%%%%%.\n"
    "               -%@%=%%@%=%@%@%@%@.\n"
    "                    #@%%  -==-\n"
    "                 +*******-%@%%:***:\n"
    "                .%@%@@%@@=%@%%-@%@-\n"
    "                 -=======:%@%%:===.\n"
    "                    #@@%  +##+\n"
    "                    *%%#"
    "\033[0m"
)

# Git-style command reference for the top-level help: each group has a title and
# a list of (signature, description). Signatures mirror the real argument order;
# [<...>] marks an optional field, <...> a placeholder the user fills in.
_HELP_GROUPS = [
    ("share agent context across sessions", [
        ("export <name> [--session <id>]", "Write a local session to a .jsonl file"),
        ("import [<file>] [-o]", "Import a .jsonl file into a new local session"),
        ("push [<remote>] <name> [--session <id>]", "Upload a local session to a remote"),
        ("pull [<remote>] <name> [-o]", "Download a remote session locally"),
    ]),
    ("manage remotes and stored sessions", [
        ("remote add <name> <url>", "Register a remote"),
        ("rm [<remote>] <name>", "Delete a session from a remote"),
        ("ls [<remote>]", "List local (or remote) sessions"),
    ]),
    ("inspect", [
        ("log", "Show history of remote operations"),
        ("help", "Show this help message"),
    ]),
]

_HELP_NOTES = [
    "Arguments shown as [<...>] are optional; <...> are placeholders you fill in.",
    "'<remote>' may be omitted when exactly one remote is configured.",
    "push omits '--session' when only one local chat exists; pass '--session <id>' when several do.",
    "Session names are letters, numbers, and hyphen; stored lowercase. Reusing a name is an error.",
    "Add '-o' / '--open' to pull to resume the session immediately with 'claude --resume'.",
    "Run 'ferry <command> -h' to see the parameters for a single command.",
    "Run 'ferry --version' to print the installed version.",
]


def _render_help():
    """Build the git-like top-level help text (ends with a trailing newline)."""
    width = max(len(sig) for _, cmds in _HELP_GROUPS for sig, _ in cmds)
    lines = [
        _FERRY_ART,
        "",
        "\033[1;36musage:\033[0m ferry <command> [<args>]",
        "",
        f"ferry -- {_TAGLINE}.",
        "",
        "\033[1mThese are the ferry commands used in various situations:\033[0m",
        "",
    ]
    for title, cmds in _HELP_GROUPS:
        lines.append(f"\033[1;32m{title}\033[0m")
        for sig, desc in cmds:
            lines.append(f"   \033[1m{sig.ljust(width)}\033[0m  {desc}")
        lines.append("")
    for note in _HELP_NOTES:
        lines.append(f"\033[2m{note}\033[0m")
    lines.append("")
    return "\n".join(lines)


def _build_parser():
    p = argparse.ArgumentParser(prog="ferry")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="<command>")

    ex = sub.add_parser("export", help="write a local session to a .jsonl file",
                        description="Export a local session to <name>.jsonl in the current folder.")
    ex.add_argument("name", metavar="<name>",
                    help="letters, numbers, hyphen; stored lowercase")
    ex.add_argument("--session", default=None, dest="session_id", metavar="<id>",
                    help="local session id to export (omit when only one local chat)")

    im = sub.add_parser("import", help="import a .jsonl file into a new local session",
                        description="Import a .jsonl file into a fresh local Claude session.")
    im.add_argument("file", nargs="?", default=None, metavar="<file>",
                    help="path to a .jsonl file (omit to pick from cwd or Downloads)")
    im.add_argument("-o", "--open", action="store_true", dest="open",
                    help="open the session with 'claude --resume' after importing")

    sp = sub.add_parser("push", help="upload a local session to a remote",
                        description="Upload a local session to a remote under <name>.")
    sp.add_argument("remote", nargs="?", default=None, metavar="<remote>",
                    help="remote name (optional when only one is configured)")
    sp.add_argument("name", metavar="<name>",
                    help="letters, numbers, hyphen; stored lowercase")
    sp.add_argument("--session", default=None, dest="session_id", metavar="<id>",
                    help="local session id to upload (omit when only one local chat; required when several)")

    pl = sub.add_parser("pull", help="download a remote session locally",
                        description="Download <name> from a remote into a fresh local session.")
    pl.add_argument("remote", nargs="?", default=None, metavar="<remote>",
                    help="remote name (optional when only one is configured)")
    pl.add_argument("name", metavar="<name>", help="name of the session on the remote")
    pl.add_argument("-o", "--open", action="store_true", dest="open",
                    help="open the session with 'claude --resume' after pulling")

    rmp = sub.add_parser("rm", help="delete a session from a remote",
                         description="Delete the session stored as <name> on a remote.")
    rmp.add_argument("remote", nargs="?", default=None, metavar="<remote>",
                     help="remote name (optional when only one is configured)")
    rmp.add_argument("name", metavar="<name>", help="name of the session on the remote")

    rm = sub.add_parser("remote", help="manage remotes",
                        description="Manage the remotes ferry can push to and pull from.")
    rmsub = rm.add_subparsers(dest="remote_cmd", required=True, metavar="<subcommand>")
    rma = rmsub.add_parser("add", help="register a remote",
                           description="Register a remote named <name> at <url>.")
    rma.add_argument("name", metavar="<name>", help="local name for the remote")
    rma.add_argument("url", metavar="<url>",
                     help="hub url (e.g. http://localhost:8080)")

    lsp = sub.add_parser("ls", help="list local (or remote) sessions",
                         description="List local sessions, or sessions on <remote> when given.")
    lsp.add_argument("remote", nargs="?", default=None, metavar="<remote>",
                     help="remote to list (omit to list local sessions)")

    sub.add_parser("log", help="show local history of remote operations",
                   description="Show the local history of push / pull / rm operations.")

    return p


def _open_session(session_id):
    """Hand off to ``claude --resume <session_id>`` (the ``-o/--open`` flag).

    Inherits the current terminal so the resumed session is interactive, and
    falls back to printing the resume command when ``claude`` is not on PATH.
    """
    try:
        subprocess.run(["claude", "--resume", session_id], check=False)
    except FileNotFoundError:
        print(f"ferry: 'claude' not found on PATH; resume manually with: "
              f"claude --resume {session_id}", file=sys.stderr)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # git-style: bare `ferry`, `ferry help`, and the help flags all print the
    # custom command reference and exit cleanly.
    if not argv or argv[0] in ("help", "-h", "--help"):
        sys.stdout.write(_render_help())
        return 0
    if argv[0] in ("--version", "-V"):
        print(f"ferry {__version__}")
        return 0

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.cmd == "export":
            path = core.export(args.name, args.session_id)
            print(path)
        elif args.cmd == "import":
            new_id, cwd = core.import_session(args.file)
            folder = cc.session_path(cwd, new_id).parent
            print(f"imported into {new_id}\n  folder: {folder}\n"
                  f"  resume: claude --resume {new_id}")
            if args.open:
                _open_session(new_id)
        elif args.cmd == "push":
            remote = core.push(args.remote, args.name, args.session_id)
            if args.session_id:
                print(f"pushed {args.session_id} -> {remote}/{args.name}")
            else:
                print(f"pushed -> {remote}/{args.name}")
        elif args.cmd == "pull":
            new_id = core.pull(args.remote, args.name)
            folder = cc.session_path(str(config.project_dir()), new_id).parent
            print(f"pulled into {new_id}\n  folder: {folder}\n"
                  f"  resume: claude --resume {new_id}")
            if args.open:
                _open_session(new_id)
        elif args.cmd == "rm":
            remote = core.rm(args.remote, args.name)
            print(f"removed {remote}/{args.name}")
        elif args.cmd == "remote":
            core.remote_add(args.name, args.url)
            print(f"remote {args.name!r} set")
        elif args.cmd == "ls":
            for sid in core.ls(args.remote):
                print(sid)
        elif args.cmd == "log":
            for e in core.log():
                suffix = f" ({e['id']})" if e.get("id") else ""
                print(f"{e.get('ts','')}  {e.get('op',''):<5} "
                      f"{e.get('remote','')}/{e.get('name','')}{suffix}")
    except ValueError as e:
        print(f"ferry: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
