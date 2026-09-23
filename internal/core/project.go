package core

import (
	"bufio"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/lindsay-cheng/ferry/internal/connector"
)

// ChatCWD returns the chat folder for export/import.
// It walks up from cwd for a .ferry directory; if found, chats belong to that
// folder's parent. Otherwise chats belong to resolved cwd.
func ChatCWD() (string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	start, err := resolvePath(cwd)
	if err != nil {
		return "", err
	}
	d := start
	for {
		ferryDir := filepath.Join(d, ".ferry")
		info, err := os.Stat(ferryDir)
		if err == nil && info.IsDir() {
			return d, nil
		}
		parent := filepath.Dir(d)
		if parent == d {
			break
		}
		d = parent
	}
	return start, nil
}

func resolvePath(path string) (string, error) {
	abs, err := filepath.Abs(path)
	if err != nil {
		return "", err
	}
	resolved, err := filepath.EvalSymlinks(abs)
	if err == nil {
		return resolved, nil
	}
	return abs, nil
}

type listedSession struct {
	ID    string
	Path  string
	Label string
	Mtime time.Time
}

// SessionListLines returns numbered labels for the local sessions of the chat folder.
// Line 1 is the most recently changed session.
func SessionListLines() ([]string, error) {
	cwd, err := ChatCWD()
	if err != nil {
		return nil, err
	}
	sessions, err := localSessions(cwd)
	if err != nil {
		return nil, err
	}
	lines := make([]string, len(sessions))
	for i, s := range sessions {
		lines[i] = formatSessionLine(i+1, s.Label)
	}
	return lines, nil
}

func localSessions(cwd string) ([]listedSession, error) {
	found, err := connector.ListForCWD(cwd)
	if err != nil {
		return nil, err
	}
	out := make([]listedSession, len(found))
	for i, s := range found {
		mt := time.Time{}
		if fi, err := os.Stat(s.Path); err == nil {
			mt = fi.ModTime()
		}
		out[i] = listedSession{ID: s.ID, Path: s.Path, Label: sessionLabel(s.Path), Mtime: mt}
	}
	sort.Slice(out, func(i, j int) bool {
		if !out[i].Mtime.Equal(out[j].Mtime) {
			return out[i].Mtime.After(out[j].Mtime)
		}
		return out[i].ID < out[j].ID
	})
	return out, nil
}

func formatSessionLine(n int, label string) string {
	return fmt.Sprintf("%d. %s", n, label)
}

// pickSession resolves a session id, a list number, or the only local session.
// Several sessions and an empty argument print the numbered list. On a terminal,
// Enter selects 1. Otherwise the caller must pass --session <number>.
func pickSession(session, cwd string, opts ImportOptions) (string, error) {
	sessions, err := localSessions(cwd)
	if err != nil {
		return "", err
	}
	if session != "" {
		for _, s := range sessions {
			if s.ID == session {
				return s.ID, nil
			}
		}
		if n, ok := digits(session); ok {
			if n < 1 || n > len(sessions) {
				return "", &FerryError{Msg: fmt.Sprintf("invalid choice: %d", n)}
			}
			return sessions[n-1].ID, nil
		}
		return session, nil
	}
	switch len(sessions) {
	case 0:
		return "", &FerryError{
			Msg: "no local Claude sessions for " + quote(cwd) + " — run Claude Code from that folder first",
		}
	case 1:
		return sessions[0].ID, nil
	}
	out := opts.ListOut
	if out == nil {
		out = os.Stdout
	}
	for i, s := range sessions {
		fmt.Fprintln(out, formatSessionLine(i+1, s.Label))
	}
	n, err := chooseIndex(len(sessions), "multiple local sessions — pass --session <number>", opts)
	if err != nil {
		return "", err
	}
	return sessions[n].ID, nil
}

func digits(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	for _, r := range s {
		if r < '0' || r > '9' {
			return 0, false
		}
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return 0, false
	}
	return n, true
}

// sessionLabel reads a title, or the first user line, from the start of the file.
func sessionLabel(path string) string {
	f, err := os.Open(path)
	if err != nil {
		return "untitled"
	}
	defer f.Close()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 0, 64*1024), 1024*1024)
	var title, userText string
	for n := 0; sc.Scan() && n < 200; n++ {
		kind, text := labelFromLine(sc.Bytes())
		if kind == "title" && text != "" && title == "" {
			title = text
			break
		}
		if kind == "user" && userText == "" {
			userText = text
		}
		if userText != "" && n >= 30 {
			break
		}
	}
	label := title
	if label == "" {
		label = userText
	}
	label = strings.Join(strings.Fields(label), " ")
	if label == "" {
		return "untitled"
	}
	return clipLabel(label, 72)
}

func labelFromLine(line []byte) (kind, text string) {
	var row struct {
		Type    string `json:"type"`
		Title   string `json:"title"`
		Message struct {
			Content json.RawMessage `json:"content"`
		} `json:"message"`
	}
	if json.Unmarshal(line, &row) != nil {
		return "", ""
	}
	if row.Type == "ai-title" {
		return "title", strings.TrimSpace(row.Title)
	}
	if row.Type == "user" {
		return "user", messageText(row.Message.Content)
	}
	return "", ""
}

func messageText(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var s string
	if json.Unmarshal(raw, &s) == nil {
		return s
	}
	var blocks []struct {
		Text string `json:"text"`
	}
	if json.Unmarshal(raw, &blocks) != nil {
		return ""
	}
	for _, b := range blocks {
		if strings.TrimSpace(b.Text) != "" {
			return b.Text
		}
	}
	return ""
}

func clipLabel(s string, max int) string {
	r := []rune(s)
	if len(r) <= max {
		return s
	}
	if max <= 3 {
		return string(r[:max])
	}
	return string(r[:max-3]) + "..."
}

func chooseIndex(count int, nonTTYMsg string, opts ImportOptions) (int, error) {
	isTTY := false
	if opts.StdinIsTTY != nil {
		isTTY = *opts.StdinIsTTY
	} else {
		isTTY = isTerminal(os.Stdin)
	}
	if !isTTY {
		return 0, &FerryError{Msg: nonTTYMsg}
	}
	choice := ""
	if opts.ReadChoice != nil {
		choice = strings.TrimSpace(opts.ReadChoice())
	} else {
		fmt.Fprint(os.Stdout, "Choice [1]: ")
		var line string
		if _, err := fmt.Scanln(&line); err != nil && !strings.Contains(err.Error(), "unexpected newline") {
			if err == io.EOF {
				return 0, &FerryError{Msg: nonTTYMsg}
			}
			return 0, err
		}
		choice = strings.TrimSpace(line)
	}
	if choice == "" {
		return 0, nil
	}
	n, err := parseChoice(choice)
	if err != nil {
		return 0, err
	}
	if n < 1 || n > count {
		return 0, &FerryError{Msg: fmt.Sprintf("invalid choice: %d", n)}
	}
	return n - 1, nil
}

func quote(s string) string {
	return "'" + s + "'"
}
