package core

import (
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strings"

	"github.com/lindsay-cheng/ferry/internal/connector"
)

var nameRE = regexp.MustCompile(`^[a-z0-9-]+$`)

// CopyFileToClipboard copies a file onto the clipboard (Darwin). Tests may replace it.
var CopyFileToClipboard = defaultCopyFileToClipboard

// exportClipboard is true when Export should copy to the clipboard. Tests may override.
var exportClipboard = func() bool { return runtime.GOOS == "darwin" }

// NormalizeExportName validates and normalizes an export basename (no .jsonl suffix).
func NormalizeExportName(name string) (string, error) {
	if name == "" {
		return "", &FerryError{Msg: "name required"}
	}
	base := name
	if strings.HasSuffix(strings.ToLower(base), ".jsonl") {
		base = base[:len(base)-6]
	}
	base = strings.ToLower(base)
	if base == "" || base == "." || base == ".." || strings.Contains(base, "/") {
		return "", &FerryError{Msg: "name must be letters, numbers, and hyphen"}
	}
	if !nameRE.MatchString(base) {
		return "", &FerryError{Msg: "name must be letters, numbers, and hyphen"}
	}
	return base, nil
}

// PrepareExportText drops a truncated last line with a warning.
func PrepareExportText(text, sessionID string) (string, []string) {
	if text == "" {
		return text, nil
	}
	lines := splitLinesKeepends(text)
	if len(lines) == 0 {
		return text, nil
	}
	lastBody := strings.TrimRight(lines[len(lines)-1], "\r\n")
	if lastBody == "" {
		return text, nil
	}
	if json.Valid([]byte(lastBody)) {
		return text, nil
	}
	warn := fmt.Sprintf("skipping invalid JSON on last line of session %s", quote(sessionID))
	return strings.Join(lines[:len(lines)-1], ""), []string{warn}
}

// Export writes a local session to <name>.jsonl in the current directory.
func Export(name, sessionID string) (string, []string, error) {
	norm, err := NormalizeExportName(name)
	if err != nil {
		return "", nil, err
	}
	chatCWD, err := ChatCWD()
	if err != nil {
		return "", nil, err
	}
	sessionID, err = pickSession(sessionID, chatCWD, ImportOptions{})
	if err != nil {
		return "", nil, err
	}
	text, err := connector.ReadText(sessionID)
	if err != nil {
		return "", nil, err
	}
	text, warns := PrepareExportText(text, sessionID)
	cwd, err := os.Getwd()
	if err != nil {
		return "", warns, err
	}
	outPath := filepath.Join(cwd, norm+".jsonl")
	if _, err := os.Stat(outPath); err == nil {
		return "", warns, &FerryError{Msg: filepath.Base(outPath) + " already exists"}
	}
	if err := os.WriteFile(outPath, []byte(text), 0o644); err != nil {
		return "", warns, err
	}
	if exportClipboard() {
		_ = CopyFileToClipboard(outPath)
	}
	abs, err := filepath.Abs(outPath)
	if err != nil {
		return outPath, warns, nil
	}
	return abs, warns, nil
}

func defaultCopyFileToClipboard(path string) error {
	resolved, err := filepath.Abs(path)
	if err != nil {
		return err
	}
	escaped := strings.ReplaceAll(resolved, "\\", "\\\\")
	escaped = strings.ReplaceAll(escaped, `"`, `\"`)
	script := fmt.Sprintf(`set the clipboard to (POSIX file "%s")`, escaped)
	cmd := exec.Command("osascript", "-e", script)
	return cmd.Run()
}
