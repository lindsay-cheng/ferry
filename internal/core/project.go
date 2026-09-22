package core

import (
	"os"
	"path/filepath"
	"sort"

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

// ListLocal returns sorted session ids for cwd.
func ListLocal(cwd string) ([]string, error) {
	sessions, err := connector.ListForCWD(cwd)
	if err != nil {
		return nil, err
	}
	ids := make([]string, len(sessions))
	for i, s := range sessions {
		ids[i] = s.ID
	}
	sort.Strings(ids)
	return ids, nil
}

// ResolveSession returns an explicit session id, or the sole local session for cwd.
func ResolveSession(session, cwd string) (string, error) {
	if session != "" {
		return session, nil
	}
	ids, err := ListLocal(cwd)
	if err != nil {
		return "", err
	}
	switch len(ids) {
	case 1:
		return ids[0], nil
	case 0:
		return "", &FerryError{
			Msg: "no local Claude sessions for " + quote(cwd) + " — run Claude Code from that folder first",
		}
	default:
		return "", &FerryError{
			Msg: "multiple local sessions for " + quote(cwd) + " (" + joinComma(ids) + "); pass --session <id>",
		}
	}
}

func quote(s string) string {
	return "'" + s + "'"
}

func joinComma(ss []string) string {
	if len(ss) == 0 {
		return ""
	}
	out := ss[0]
	for i := 1; i < len(ss); i++ {
		out += ", " + ss[i]
	}
	return out
}
