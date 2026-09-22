package core

import (
	"crypto/rand"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/lindsay-cheng/ferry/internal/connector"
)

// ImportOptions controls import path discovery when file is omitted.
type ImportOptions struct {
	StdinIsTTY *bool
	ReadChoice func() string
	ListOut    io.Writer
}

// ImportSession imports a jsonl file into a fresh local session.
// It returns the new session id, chat cwd, and any rewrite warnings.
func ImportSession(file string, opts ImportOptions) (string, string, []string, error) {
	path, err := resolveImportPath(file, opts)
	if err != nil {
		return "", "", nil, err
	}
	text, err := os.ReadFile(path)
	if err != nil {
		return "", "", nil, err
	}
	chatCWD, err := ChatCWD()
	if err != nil {
		return "", "", nil, err
	}
	newID, warns, err := writeImportedText(string(text), chatCWD, "import")
	if err != nil {
		return "", "", warns, err
	}
	return newID, chatCWD, warns, nil
}

func writeImportedText(text, cwd, source string) (string, []string, error) {
	newID := NewID()
	rewritten, warns, err := RewriteText(text, newID, cwd, source)
	if err != nil {
		return "", warns, err
	}
	path := connector.SessionPath(cwd, newID)
	_, err = connector.WriteText(path, rewritten)
	if err != nil {
		return "", warns, err
	}
	return newID, warns, nil
}

// NewID returns a new random UUID v4 string.
func NewID() string {
	var b [16]byte
	_, _ = rand.Read(b[:])
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		b[0:4], b[4:6], b[6:8], b[8:10], b[10:16])
}

type candidate struct {
	path  string
	mtime time.Time
}

func jsonlImportCandidates() ([]candidate, error) {
	var found []candidate
	cwd, err := os.Getwd()
	if err != nil {
		return nil, err
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return nil, err
	}
	downloads := filepath.Join(home, "Downloads")
	for _, folder := range []string{cwd, downloads} {
		info, err := os.Stat(folder)
		if err != nil || !info.IsDir() {
			continue
		}
		entries, err := os.ReadDir(folder)
		if err != nil {
			continue
		}
		for _, ent := range entries {
			if ent.IsDir() {
				continue
			}
			name := ent.Name()
			if !strings.HasSuffix(name, ".jsonl") {
				continue
			}
			if strings.HasSuffix(name, ".crdownload") {
				continue
			}
			full := filepath.Join(folder, name)
			fi, err := os.Stat(full)
			if err != nil || !fi.Mode().IsRegular() {
				continue
			}
			found = append(found, candidate{path: full, mtime: fi.ModTime()})
		}
	}
	sort.Slice(found, func(i, j int) bool {
		return found[i].mtime.After(found[j].mtime)
	})
	return found, nil
}

func formatImportCandidate(index int, path string) string {
	return fmt.Sprintf("%d. %s %s", index, filepath.Dir(path), filepath.Base(path))
}

func resolveImportPath(file string, opts ImportOptions) (string, error) {
	if file != "" {
		info, err := os.Stat(file)
		if err != nil || !info.Mode().IsRegular() {
			return "", &FerryError{Msg: "file not found: " + file}
		}
		return file, nil
	}
	candidates, err := jsonlImportCandidates()
	if err != nil {
		return "", err
	}
	if len(candidates) == 0 {
		return "", &FerryError{Msg: "no .jsonl file in current folder or Downloads — pass a path"}
	}
	if len(candidates) == 1 {
		return candidates[0].path, nil
	}
	out := opts.ListOut
	if out == nil {
		out = os.Stdout
	}
	for i, c := range candidates {
		fmt.Fprintln(out, formatImportCandidate(i+1, c.path))
	}
	isTTY := false
	if opts.StdinIsTTY != nil {
		isTTY = *opts.StdinIsTTY
	} else {
		fi, err := os.Stdin.Stat()
		isTTY = err == nil && (fi.Mode()&os.ModeCharDevice) != 0
	}
	if !isTTY {
		return "", &FerryError{Msg: "multiple .jsonl files — pass a path or a number"}
	}
	choice := ""
	if opts.ReadChoice != nil {
		choice = strings.TrimSpace(opts.ReadChoice())
	} else {
		fmt.Fprint(os.Stdout, "Choice [1]: ")
		var line string
		if _, err := fmt.Scanln(&line); err != nil && !strings.Contains(err.Error(), "unexpected newline") {
			return "", err
		}
		choice = strings.TrimSpace(line)
	}
	if choice == "" {
		return candidates[0].path, nil
	}
	n, err := parseChoice(choice)
	if err != nil {
		return "", err
	}
	if n < 1 || n > len(candidates) {
		return "", &FerryError{Msg: fmt.Sprintf("invalid choice: %d", n)}
	}
	return candidates[n-1].path, nil
}

func parseChoice(choice string) (int, error) {
	var n int
	_, err := fmt.Sscanf(choice, "%d", &n)
	if err != nil {
		return 0, &FerryError{Msg: "invalid choice: " + quote(choice)}
	}
	return n, nil
}
