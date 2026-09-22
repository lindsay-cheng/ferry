package core

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

var (
	ErrInvalidJSON = errors.New("invalid json")
	ErrNoHistory   = errors.New("file has no chat history")
)

// RewriteLine rewrites cwd and sessionId on one jsonl line when present.
// It returns ErrInvalidJSON when the line is not valid JSON.
func RewriteLine(line, newID, cwd string) (string, error) {
	var obj any
	if err := json.Unmarshal([]byte(line), &obj); err != nil {
		return "", ErrInvalidJSON
	}
	m, ok := obj.(map[string]any)
	if ok {
		_, hasCWD := m["cwd"]
		_, hasSession := m["sessionId"]
		if hasCWD || hasSession {
			if hasCWD {
				m["cwd"] = cwd
			}
			if hasSession {
				m["sessionId"] = newID
			}
			var buf bytes.Buffer
			enc := json.NewEncoder(&buf)
			enc.SetEscapeHTML(false)
			if err := enc.Encode(m); err != nil {
				return "", err
			}
			return strings.TrimRight(buf.String(), "\n") + "\n", nil
		}
	}
	if strings.HasSuffix(line, "\n") {
		return line, nil
	}
	return line + "\n", nil
}

// RewriteText rewrites a whole jsonl file the way import does.
// Empty lines are skipped. Invalid JSON lines are dropped.
// A warning is appended when the last line has invalid JSON.
func RewriteText(text, newID, cwd, source string) (string, []string, error) {
	lines := splitLinesKeepends(text)
	if len(lines) == 0 && text != "" {
		lines = []string{text}
	}
	var out strings.Builder
	var warns []string
	for i, raw := range lines {
		line := strings.TrimRight(raw, "\r\n")
		if line == "" {
			continue
		}
		rewritten, err := RewriteLine(line, newID, cwd)
		if err != nil {
			if i == len(lines)-1 {
				warns = append(warns, fmt.Sprintf("skipping invalid JSON on last line of %s", source))
			}
			continue
		}
		out.WriteString(rewritten)
	}
	if out.Len() == 0 {
		return "", warns, ErrNoHistory
	}
	return out.String(), warns, nil
}

func splitLinesKeepends(s string) []string {
	if s == "" {
		return nil
	}
	var lines []string
	start := 0
	for i := 0; i < len(s); i++ {
		if s[i] == '\n' {
			lines = append(lines, s[start:i+1])
			start = i + 1
		}
	}
	if start < len(s) {
		lines = append(lines, s[start:])
	}
	return lines
}
