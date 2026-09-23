package cli

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"

	"github.com/lindsay-cheng/ferry/internal/connector"
	"github.com/lindsay-cheng/ferry/internal/core"
)

const Version = "0.1.1"

const tagline = "git for your Claude Code agent context"

type helpCmd struct {
	sig  string
	desc string
}

type helpGroup struct {
	title string
	cmds  []helpCmd
}

var helpGroups = []helpGroup{
	{
		title: "share agent context across sessions",
		cmds: []helpCmd{
			{"export <name> [--session <number>]", "Write a local session to a .jsonl file"},
			{"import [<file>] [-o]", "Import a .jsonl file into a new local session"},
		},
	},
	{
		title: "manage stored sessions",
		cmds: []helpCmd{
			{"ls", "List local sessions by number"},
		},
	},
	{
		title: "inspect",
		cmds: []helpCmd{
			{"help", "Show this help message"},
		},
	},
}

var helpNotes = []string{
	"Arguments shown as [<...>] are optional; <...> are placeholders you fill in.",
	"When several local sessions exist, export prints a numbered list. Pass '--session <number>', or press Enter to take 1 (the newest).",
	"Session names are letters, numbers, and hyphen; stored lowercase. Reusing a name is an error.",
	"Add '-o' / '--open' to import to resume the session immediately with 'claude --resume'.",
	"Run 'ferry --version' to print the installed version.",
}

// runClaude runs claude --resume. Tests may replace it.
var runClaude = defaultRunClaude

// Main is the ferry CLI entry point.
func Main(argv []string) int {
	if len(argv) == 0 || argv[0] == "help" || argv[0] == "-h" || argv[0] == "--help" {
		fmt.Print(renderHelp())
		return 0
	}
	if argv[0] == "--version" || argv[0] == "-V" {
		fmt.Printf("ferry %s\n", Version)
		return 0
	}
	switch argv[0] {
	case "export":
		return cmdExport(argv[1:])
	case "import":
		return cmdImport(argv[1:])
	case "ls":
		return cmdLs(argv[1:])
	default:
		return failMsg("unknown command: " + argv[0])
	}
}

func renderHelp() string {
	width := 0
	for _, g := range helpGroups {
		for _, c := range g.cmds {
			if len(c.sig) > width {
				width = len(c.sig)
			}
		}
	}
	var b strings.Builder
	b.WriteString("\033[1;36musage:\033[0m ferry <command> [<args>]\n\n")
	b.WriteString("ferry -- ")
	b.WriteString(tagline)
	b.WriteString(".\n\n")
	b.WriteString("\033[1mThese are the ferry commands used in various situations:\033[0m\n\n")
	for _, g := range helpGroups {
		b.WriteString("\033[1;32m")
		b.WriteString(g.title)
		b.WriteString("\033[0m\n")
		for _, c := range g.cmds {
			b.WriteString("   \033[1m")
			b.WriteString(c.sig)
			b.WriteString(strings.Repeat(" ", width-len(c.sig)))
			b.WriteString("\033[0m  ")
			b.WriteString(c.desc)
			b.WriteByte('\n')
		}
		b.WriteByte('\n')
	}
	for _, note := range helpNotes {
		b.WriteString("\033[2m")
		b.WriteString(note)
		b.WriteString("\033[0m\n")
	}
	b.WriteByte('\n')
	return b.String()
}

func cmdExport(args []string) int {
	name := ""
	session := ""
	for i := 0; i < len(args); i++ {
		a := args[i]
		if a == "--session" {
			if i+1 >= len(args) {
				return failMsg("--session requires an argument")
			}
			session = args[i+1]
			i++
			continue
		}
		if strings.HasPrefix(a, "-") {
			return failMsg("unknown flag: " + a)
		}
		if name != "" {
			return failMsg("too many arguments")
		}
		name = a
	}
	if name == "" {
		return failMsg("name required")
	}
	path, warns, err := core.Export(name, session)
	for _, w := range warns {
		fmt.Fprintln(os.Stderr, w)
	}
	if err != nil {
		return fail(err)
	}
	fmt.Println(path)
	return 0
}

func cmdImport(args []string) int {
	open := false
	file := ""
	for _, a := range args {
		switch a {
		case "-o", "--open":
			open = true
		default:
			if strings.HasPrefix(a, "-") {
				return failMsg("unknown flag: " + a)
			}
			if file != "" {
				return failMsg("too many arguments")
			}
			file = a
		}
	}
	newID, cwd, warns, err := core.ImportSession(file, core.ImportOptions{})
	for _, w := range warns {
		fmt.Fprintln(os.Stderr, w)
	}
	if err != nil {
		return fail(err)
	}
	folder := filepath.Dir(connector.SessionPath(cwd, newID))
	fmt.Printf("imported into %s\n  folder: %s\n  resume: claude --resume %s\n", newID, folder, newID)
	if open {
		openSession(newID)
	}
	return 0
}

func cmdLs(args []string) int {
	if len(args) != 0 {
		return failMsg("unexpected arguments")
	}
	lines, err := core.SessionListLines()
	if err != nil {
		return fail(err)
	}
	for _, line := range lines {
		fmt.Println(line)
	}
	return 0
}

func openSession(sessionID string) {
	if err := runClaude(sessionID); err != nil {
		fmt.Fprintf(os.Stderr,
			"ferry: 'claude' not found on PATH; resume manually with: claude --resume %s\n",
			sessionID)
	}
}

func defaultRunClaude(sessionID string) error {
	path, err := exec.LookPath("claude")
	if err != nil {
		return err
	}
	cmd := exec.Command(path, "--resume", sessionID)
	cmd.Stdin = os.Stdin
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	_ = cmd.Run()
	return nil
}

func fail(err error) int {
	fmt.Fprintf(os.Stderr, "ferry: %s\n", err.Error())
	return 1
}

func failMsg(msg string) int {
	return fail(&core.FerryError{Msg: msg})
}
