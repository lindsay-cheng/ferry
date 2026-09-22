// Package connector is a dumb I/O boundary for Claude Code session JSONL files.
package connector

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

var encodeRE = regexp.MustCompile(`[^A-Za-z0-9]`)

// ErrSessionNotFound means a read target (session id or path) does not exist.
var ErrSessionNotFound = errors.New("session not found")

// ErrAmbiguousSession means a session id matches files in more than one project dir.
var ErrAmbiguousSession = errors.New("ambiguous session")

// ProjectsRoot returns $CLAUDE_CONFIG_DIR/projects if set, else ~/.claude/projects.
func ProjectsRoot() string {
	base := os.Getenv("CLAUDE_CONFIG_DIR")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			base = filepath.Join("~", ".claude")
		} else {
			base = filepath.Join(home, ".claude")
		}
	}
	return filepath.Join(base, "projects")
}

// EncodeCWD is the Claude Code project-dir encoding: non-alphanumeric runes become '-'.
func EncodeCWD(cwd string) string {
	return encodeRE.ReplaceAllString(cwd, "-")
}

// SessionPath is where a session for cwd with sessionID lives on this machine.
func SessionPath(cwd, sessionID string) string {
	return filepath.Join(ProjectsRoot(), EncodeCWD(cwd), sessionID+".jsonl")
}

// Resolve returns the path of the session with this id, or "" when absent.
// It returns ErrAmbiguousSession when the id exists in more than one project dir.
func Resolve(sessionID string) (string, error) {
	root := ProjectsRoot()
	pattern := filepath.Join(root, "*", sessionID+".jsonl")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return "", err
	}
	sort.Strings(matches)
	if len(matches) == 0 {
		return "", nil
	}
	if len(matches) > 1 {
		names := make([]string, len(matches))
		for i, m := range matches {
			names[i] = filepath.Base(filepath.Dir(m))
		}
		return "", fmt.Errorf("%w: session id %q found in %d project dirs: %s",
			ErrAmbiguousSession, sessionID, len(matches), strings.Join(names, ", "))
	}
	return matches[0], nil
}

// Session is one local session file (id and absolute or relative path).
type Session struct {
	ID   string
	Path string
}

// ListSessions returns every session file under the root, sorted by path.
func ListSessions() ([]Session, error) {
	root := ProjectsRoot()
	pattern := filepath.Join(root, "*", "*.jsonl")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}
	sort.Strings(matches)
	out := make([]Session, len(matches))
	for i, p := range matches {
		out[i] = Session{ID: strings.TrimSuffix(filepath.Base(p), ".jsonl"), Path: p}
	}
	return out, nil
}

// ListForCWD returns sessions for one cwd project dir, sorted by path.
func ListForCWD(cwd string) ([]Session, error) {
	proj := filepath.Join(ProjectsRoot(), EncodeCWD(cwd))
	pattern := filepath.Join(proj, "*.jsonl")
	matches, err := filepath.Glob(pattern)
	if err != nil {
		return nil, err
	}
	sort.Strings(matches)
	out := make([]Session, len(matches))
	for i, p := range matches {
		out[i] = Session{ID: strings.TrimSuffix(filepath.Base(p), ".jsonl"), Path: p}
	}
	return out, nil
}

// ReadText reads a session's JSONL. session is a session id or a path: if it
// contains a path separator or ends with ".jsonl" it is treated as a path.
func ReadText(session string) (string, error) {
	var path string
	if strings.Contains(session, string(os.PathSeparator)) || strings.HasSuffix(session, ".jsonl") {
		path = session
	} else {
		resolved, err := Resolve(session)
		if err != nil {
			return "", err
		}
		if resolved == "" {
			return "", fmt.Errorf("%w: no session with id %q", ErrSessionNotFound, session)
		}
		path = resolved
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, fs.ErrNotExist) {
			return "", fmt.Errorf("%w: no session file at %q", ErrSessionNotFound, path)
		}
		return "", err
	}
	return string(data), nil
}

// WriteText atomically writes text to path, creating parent dirs. Overwrites
// unconditionally and writes the string exactly as given. Returns path.
func WriteText(path, text string) (string, error) {
	path = filepath.Clean(path)
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), filepath.Base(path)+".*.tmp")
	if err != nil {
		return "", err
	}
	tmpPath := tmp.Name()
	ok := false
	defer func() {
		if !ok {
			_ = os.Remove(tmpPath)
		}
	}()
	if _, err := tmp.WriteString(text); err != nil {
		_ = tmp.Close()
		return "", err
	}
	if err := tmp.Close(); err != nil {
		return "", err
	}
	if err := os.Rename(tmpPath, path); err != nil {
		return "", err
	}
	ok = true
	return path, nil
}
