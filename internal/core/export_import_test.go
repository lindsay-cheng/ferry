package core

import (
	"bytes"
	"encoding/json"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/lindsay-cheng/ferry/internal/connector"
)

const validEntry = `{"parentUuid":null,"type":"user","uuid":"u1",` +
	`"cwd":"/Users/alice/proj","sessionId":"alice-sess",` +
	`"timestamp":"2026-06-26T10:00:00.000Z",` +
	`"message":{"role":"user","content":"hi"}}` + "\n"

type exportImportBase struct {
	t      *testing.T
	tmp    string
	origWD string
}

func newExportImportBase(t *testing.T) *exportImportBase {
	t.Helper()
	b := &exportImportBase{t: t, tmp: t.TempDir()}
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(b.tmp, "claude"))
	t.Setenv("HOME", b.tmp)
	if err := os.MkdirAll(filepath.Join(b.tmp, "Downloads"), 0o755); err != nil {
		t.Fatal(err)
	}
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	b.origWD = wd
	t.Cleanup(func() { _ = os.Chdir(b.origWD) })
	return b
}

func (b *exportImportBase) chdir(dir string) {
	if err := os.Chdir(dir); err != nil {
		b.t.Fatal(err)
	}
}

func (b *exportImportBase) seedSession(cwd, sessionID, text string) {
	path := connector.SessionPath(cwd, sessionID)
	if _, err := connector.WriteText(path, text); err != nil {
		b.t.Fatal(err)
	}
}

func parseSessionLines(t *testing.T, path string) []map[string]any {
	t.Helper()
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var out []map[string]any
	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		var obj map[string]any
		if err := json.Unmarshal([]byte(line), &obj); err != nil {
			t.Fatalf("parse line: %v", err)
		}
		out = append(out, obj)
	}
	return out
}

func TestExportWritesNamedFileAndSkipsTruncatedLastLine(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "sess-1", `{"uuid":"x"}`+"\n"+`{"truncated":`)
	path, warns, err := Export("My-Chat", "sess-1")
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasSuffix(path, "my-chat.jsonl") {
		t.Fatalf("path = %q", path)
	}
	got, err := os.ReadFile(filepath.Join(b.tmp, "my-chat.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"uuid":"x"}`+"\n" {
		t.Fatalf("content = %q", got)
	}
	if len(warns) != 1 {
		t.Fatalf("warns = %v, want 1", warns)
	}
}

func TestExportTwoLocalChatsWithoutSessionRaises(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "old-sess", `{"uuid":"old"}`+"\n")
	b.seedSession(chat, "new-sess", `{"uuid":"new"}`+"\n")
	_, _, err = Export("chat", "")
	if err == nil {
		t.Fatal("expected error")
	}
	msg := err.Error()
	if !strings.Contains(msg, "pass --session <number>") {
		t.Fatalf("msg = %q", msg)
	}
	if strings.Contains(msg, "old-sess") || strings.Contains(msg, "new-sess") {
		t.Fatalf("msg dumps session ids: %q", msg)
	}
}

func TestExportSessionNumberUsesNewestFirst(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "old-sess", `{"type":"user","message":{"content":"old prompt"}}`+"\n")
	b.seedSession(chat, "new-sess", `{"type":"ai-title","title":"new title"}`+"\n"+
		`{"type":"user","message":{"content":"new prompt"}}`+"\n")
	past := time.Now().Add(-2 * time.Hour)
	if err := os.Chtimes(connector.SessionPath(chat, "old-sess"), past, past); err != nil {
		t.Fatal(err)
	}
	lines, err := SessionListLines()
	if err != nil {
		t.Fatal(err)
	}
	if len(lines) != 2 || lines[0] != "1. new title" || lines[1] != "2. old prompt" {
		t.Fatalf("lines = %#v", lines)
	}
	if _, _, err := Export("picked", "1"); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(b.tmp, "picked.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(got), "new title") {
		t.Fatalf("exported the wrong session: %s", got)
	}
	id, err := pickSession("old-sess", chat, ImportOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if id != "old-sess" {
		t.Fatalf("id = %q", id)
	}
	if _, err := pickSession("9", chat, ImportOptions{}); err == nil {
		t.Fatal("expected invalid choice")
	}
	tty := true
	var buf bytes.Buffer
	id, err = pickSession("", chat, ImportOptions{
		StdinIsTTY: &tty,
		ReadChoice: func() string { return "" },
		ListOut:    &buf,
	})
	if err != nil {
		t.Fatal(err)
	}
	if id != "new-sess" {
		t.Fatalf("default choice = %q", id)
	}
	if !strings.Contains(buf.String(), "1. new title") {
		t.Fatalf("list = %q", buf.String())
	}
}

func TestExportSecondNumberAndPromptSelectOlder(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "old-sess", `{"type":"user","message":{"content":"old prompt"}}`+"\n")
	b.seedSession(chat, "new-sess", `{"type":"user","message":{"content":"new prompt"}}`+"\n")
	past := time.Now().Add(-2 * time.Hour)
	if err := os.Chtimes(connector.SessionPath(chat, "old-sess"), past, past); err != nil {
		t.Fatal(err)
	}
	if _, _, err := Export("second", "2"); err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(b.tmp, "second.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(got), "old prompt") || strings.Contains(string(got), "new prompt") {
		t.Fatalf("exported the wrong session: %s", got)
	}
	tty := true
	id, err := pickSession("", chat, ImportOptions{
		StdinIsTTY: &tty,
		ReadChoice: func() string { return "2" },
		ListOut:    io.Discard,
	})
	if err != nil {
		t.Fatal(err)
	}
	if id != "old-sess" {
		t.Fatalf("prompt choice = %q", id)
	}
}

func TestExportPromptRejectsOutOfRange(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "a-sess", `{"uuid":"a"}`+"\n")
	b.seedSession(chat, "b-sess", `{"uuid":"b"}`+"\n")
	tty := true
	_, err = pickSession("", chat, ImportOptions{
		StdinIsTTY: &tty,
		ReadChoice: func() string { return "9" },
		ListOut:    io.Discard,
	})
	if err == nil || !strings.Contains(err.Error(), "invalid choice: 9") {
		t.Fatalf("err = %v", err)
	}
}

func TestSessionLabelUsesTextBlocks(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "block-sess", `{"type":"user","message":{"content":[{"type":"text","text":"block prompt"}]}}`+"\n")
	lines, err := SessionListLines()
	if err != nil {
		t.Fatal(err)
	}
	if len(lines) != 1 || lines[0] != "1. block prompt" {
		t.Fatalf("lines = %#v", lines)
	}
}

func TestSessionListSameMtimeOrdersByID(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "b-sess", `{"type":"user","message":{"content":"beta"}}`+"\n")
	b.seedSession(chat, "a-sess", `{"type":"user","message":{"content":"alpha"}}`+"\n")
	same := time.Unix(100, 0)
	for _, id := range []string{"a-sess", "b-sess"} {
		if err := os.Chtimes(connector.SessionPath(chat, id), same, same); err != nil {
			t.Fatal(err)
		}
	}
	lines, err := SessionListLines()
	if err != nil {
		t.Fatal(err)
	}
	if len(lines) != 2 || lines[0] != "1. alpha" || lines[1] != "2. beta" {
		t.Fatalf("lines = %#v", lines)
	}
}

func TestExportNoLocalSessions(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	_, _, err := Export("chat", "")
	if err == nil || !strings.Contains(err.Error(), "no local Claude sessions") {
		t.Fatalf("err = %v", err)
	}
}

func TestExportWithoutFerryUsesCWD(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "only", `{"uuid":"o"}`+"\n")
	path, _, err := Export("solo", "")
	if err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(b.tmp, "solo.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"uuid":"o"}`+"\n" {
		t.Fatalf("content = %q", got)
	}
	if !strings.HasSuffix(path, "solo.jsonl") {
		t.Fatalf("path = %q", path)
	}
}

func TestExportFromNestedDirUsesProjectRoot(t *testing.T) {
	b := newExportImportBase(t)
	repo := filepath.Join(b.tmp, "repo")
	src := filepath.Join(repo, "app", "src")
	if err := os.MkdirAll(filepath.Join(repo, ".ferry"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(src, 0o755); err != nil {
		t.Fatal(err)
	}
	b.chdir(src)
	project, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(project, "only", `{"uuid":"o"}`+"\n")
	path, _, err := Export("nested", "")
	if err != nil {
		t.Fatal(err)
	}
	got, err := os.ReadFile(filepath.Join(src, "nested.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if string(got) != `{"uuid":"o"}`+"\n" {
		t.Fatalf("content = %q", got)
	}
	if !strings.HasSuffix(path, "nested.jsonl") {
		t.Fatalf("path = %q", path)
	}
}

func TestExportExistingFileRaises(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "s1", `{"uuid":"x"}`+"\n")
	if err := os.WriteFile(filepath.Join(b.tmp, "chat.jsonl"), []byte("old\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	_, _, err = Export("chat", "s1")
	if err == nil {
		t.Fatal("expected error")
	}
}

func TestImportWithPathRewritesAndKeepsExtraTypes(t *testing.T) {
	b := newExportImportBase(t)
	extra := testdata(t, "extra-types.jsonl")
	b.chdir(b.tmp)
	inPath := filepath.Join(b.tmp, "in.jsonl")
	if err := os.WriteFile(inPath, []byte(extra), 0o644); err != nil {
		t.Fatal(err)
	}
	newID, cwd, _, err := ImportSession(inPath, ImportOptions{})
	if err != nil {
		t.Fatal(err)
	}
	path := connector.SessionPath(cwd, newID)
	entries := parseSessionLines(t, path)
	types := make([]string, len(entries))
	for i, e := range entries {
		types[i] = e["type"].(string)
	}
	wantTypes := []string{"ai-title", "file-history-snapshot", "mode", "permission-mode", "user"}
	if strings.Join(types, ",") != strings.Join(wantTypes, ",") {
		t.Fatalf("types = %v, want %v", types, wantTypes)
	}
	for _, e := range entries {
		if _, ok := e["cwd"]; !ok {
			continue
		}
		if e["cwd"] != cwd {
			t.Fatalf("cwd = %v, want %q", e["cwd"], cwd)
		}
		if e["sessionId"] != newID {
			t.Fatalf("sessionId = %v, want %q", e["sessionId"], newID)
		}
	}
}

func TestImportNoPathOneFileInCWD(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	if err := os.WriteFile(filepath.Join(b.tmp, "solo.jsonl"), []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	tty := false
	newID, _, _, err := ImportSession("", ImportOptions{StdinIsTTY: &tty})
	if err != nil {
		t.Fatal(err)
	}
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(connector.SessionPath(chat, newID)); err != nil {
		t.Fatal(err)
	}
}

func TestImportNoPathOneFileInDownloads(t *testing.T) {
	b := newExportImportBase(t)
	empty := filepath.Join(b.tmp, "empty")
	if err := os.MkdirAll(empty, 0o755); err != nil {
		t.Fatal(err)
	}
	b.chdir(empty)
	if err := os.WriteFile(filepath.Join(b.tmp, "Downloads", "solo.jsonl"), []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	tty := false
	newID, cwd, _, err := ImportSession("", ImportOptions{StdinIsTTY: &tty})
	if err != nil {
		t.Fatal(err)
	}
	wantCWD, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if cwd != wantCWD {
		t.Fatalf("cwd = %q, want %q", cwd, wantCWD)
	}
	if _, err := os.Stat(connector.SessionPath(cwd, newID)); err != nil {
		t.Fatal(err)
	}
}

func TestIsTerminalPipeIsNotTTY(t *testing.T) {
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	defer w.Close()
	if isTerminal(r) {
		t.Fatal("pipe read end should not be a terminal")
	}
}

func TestImportNoPathTwoFilesNonTTYListsAndRaises(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	a := filepath.Join(b.tmp, "a.jsonl")
	c := filepath.Join(b.tmp, "b.jsonl")
	if err := os.WriteFile(a, []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(c, []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(a, time.Unix(1, 0), time.Unix(1, 0)); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(c, time.Unix(2, 0), time.Unix(2, 0)); err != nil {
		t.Fatal(err)
	}
	var buf bytes.Buffer
	tty := false
	_, _, _, err := ImportSession("", ImportOptions{StdinIsTTY: &tty, ListOut: &buf})
	if err == nil {
		t.Fatal("expected error")
	}
	text := buf.String()
	if !strings.Contains(text, "1.") || !strings.Contains(text, "2.") {
		t.Fatalf("listing missing numbers: %q", text)
	}
	if !strings.Contains(text, "a.jsonl") || !strings.Contains(text, "b.jsonl") {
		t.Fatalf("listing missing files: %q", text)
	}
	if !strings.Contains(err.Error(), "pass a path or a number") {
		t.Fatalf("err = %q", err.Error())
	}
}

func TestImportNoPathTTYEmptyChoicePicksFirst(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	a := filepath.Join(b.tmp, "a.jsonl")
	c := filepath.Join(b.tmp, "b.jsonl")
	if err := os.WriteFile(a, []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(c, []byte(`{"uuid":"b"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(a, time.Unix(2, 0), time.Unix(2, 0)); err != nil {
		t.Fatal(err)
	}
	if err := os.Chtimes(c, time.Unix(1, 0), time.Unix(1, 0)); err != nil {
		t.Fatal(err)
	}
	tty := true
	newID, _, _, err := ImportSession("", ImportOptions{
		StdinIsTTY: &tty,
		ReadChoice: func() string { return "" },
		ListOut:    io.Discard,
	})
	if err != nil {
		t.Fatal(err)
	}
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(connector.SessionPath(chat, newID)); err != nil {
		t.Fatal(err)
	}
}

func TestImportWithoutFerryConfig(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	inPath := filepath.Join(b.tmp, "in.jsonl")
	if err := os.WriteFile(inPath, []byte(validEntry), 0o644); err != nil {
		t.Fatal(err)
	}
	newID, cwd, _, err := ImportSession(inPath, ImportOptions{})
	if err != nil {
		t.Fatal(err)
	}
	wantCWD, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if cwd != wantCWD {
		t.Fatalf("cwd = %q, want %q", cwd, wantCWD)
	}
	if _, err := os.Stat(connector.SessionPath(cwd, newID)); err != nil {
		t.Fatal(err)
	}
}

func TestExportImportRoundtrip(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "sess-1", validEntry)
	exportPath, _, err := Export("trip", "sess-1")
	if err != nil {
		t.Fatal(err)
	}
	other := filepath.Join(b.tmp, "other")
	if err := os.MkdirAll(other, 0o755); err != nil {
		t.Fatal(err)
	}
	b.chdir(other)
	newID, cwd, _, err := ImportSession(exportPath, ImportOptions{})
	if err != nil {
		t.Fatal(err)
	}
	wantCWD, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if cwd != wantCWD {
		t.Fatalf("cwd = %q, want %q", cwd, wantCWD)
	}
	path := connector.SessionPath(cwd, newID)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	line := strings.TrimSpace(string(data))
	var entry map[string]any
	if err := json.Unmarshal([]byte(line), &entry); err != nil {
		t.Fatal(err)
	}
	if entry["cwd"] != cwd {
		t.Fatalf("cwd = %v, want %q", entry["cwd"], cwd)
	}
	if entry["sessionId"] != newID {
		t.Fatalf("sessionId = %v, want %q", entry["sessionId"], newID)
	}
}

func TestExportClipboardFailureStillWrites(t *testing.T) {
	b := newExportImportBase(t)
	b.chdir(b.tmp)
	chat, err := ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	b.seedSession(chat, "s1", `{"uuid":"x"}`+"\n")
	oldCopy := CopyFileToClipboard
	oldClip := exportClipboard
	CopyFileToClipboard = func(string) error { return os.ErrInvalid }
	exportClipboard = func() bool { return true }
	defer func() {
		CopyFileToClipboard = oldCopy
		exportClipboard = oldClip
	}()
	path, _, err := Export("chat", "s1")
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(path); err != nil {
		t.Fatal(err)
	}
}
