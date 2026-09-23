package cli

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"

	"github.com/lindsay-cheng/ferry/internal/connector"
	"github.com/lindsay-cheng/ferry/internal/core"
)

var ansiRE = regexp.MustCompile(`\x1b\[[0-9;]*m`)

func stripANSI(s string) string {
	return ansiRE.ReplaceAllString(s, "")
}

type cliBase struct {
	t      *testing.T
	tmp    string
	repo   string
	origWD string
}

func newCLIBase(t *testing.T) *cliBase {
	t.Helper()
	b := &cliBase{t: t, tmp: t.TempDir()}
	t.Setenv("CLAUDE_CONFIG_DIR", filepath.Join(b.tmp, "claude"))
	t.Setenv("HOME", b.tmp)
	if err := os.MkdirAll(filepath.Join(b.tmp, "Downloads"), 0o755); err != nil {
		t.Fatal(err)
	}
	b.repo = filepath.Join(b.tmp, "proj")
	if err := os.MkdirAll(b.repo, 0o755); err != nil {
		t.Fatal(err)
	}
	wd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	b.origWD = wd
	if err := os.Chdir(b.repo); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chdir(b.origWD) })
	return b
}

func captureStdout(fn func()) string {
	old := os.Stdout
	r, w, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	os.Stdout = w
	fn()
	_ = w.Close()
	os.Stdout = old
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

func captureStderr(fn func()) string {
	old := os.Stderr
	r, w, err := os.Pipe()
	if err != nil {
		panic(err)
	}
	os.Stderr = w
	fn()
	_ = w.Close()
	os.Stderr = old
	var buf bytes.Buffer
	_, _ = buf.ReadFrom(r)
	return buf.String()
}

func TestHelpListsExportImport(t *testing.T) {
	out := captureStdout(func() { _ = Main([]string{"help"}) })
	text := stripANSI(out)
	for _, want := range []string{"export", "import", "usage: ferry"} {
		if !strings.Contains(text, want) {
			t.Fatalf("help missing %q:\n%s", want, text)
		}
	}
}

func TestHelpOmitsPushPullHub(t *testing.T) {
	out := captureStdout(func() { _ = Main([]string{"help"}) })
	text := strings.ToLower(stripANSI(out))
	for _, bad := range []string{"push", "pull", "hub", "remote add", "ferry-hub", "log"} {
		if strings.Contains(text, bad) {
			t.Fatalf("help should not mention %q:\n%s", bad, text)
		}
	}
}

func TestVersionFlag(t *testing.T) {
	out := captureStdout(func() {
		if rc := Main([]string{"--version"}); rc != 0 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(out, "ferry 0.1.1") {
		t.Fatalf("version output = %q", out)
	}
}

func TestExportWritesFile(t *testing.T) {
	b := newCLIBase(t)
	chat, err := core.ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	path := connector.SessionPath(chat, "s1")
	if _, err := connector.WriteText(path, `{"uuid":"x"}`+"\n"); err != nil {
		t.Fatal(err)
	}
	out := captureStdout(func() {
		if rc := Main([]string{"export", "mine", "--session", "s1"}); rc != 0 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(out, "mine.jsonl") {
		t.Fatalf("stdout = %q", out)
	}
	data, err := os.ReadFile(filepath.Join(b.repo, "mine.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != `{"uuid":"x"}`+"\n" {
		t.Fatalf("content = %q", data)
	}
}

func TestImportPrintsFolderAndResume(t *testing.T) {
	b := newCLIBase(t)
	in := filepath.Join(b.tmp, "in.jsonl")
	if err := os.WriteFile(in, []byte(
		`{"parentUuid":null,"type":"user","uuid":"u1","cwd":"/a",`+
			`"sessionId":"s","timestamp":"2026-06-26T10:00:00.000Z",`+
			`"message":{"role":"user","content":"hi"}}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	chat, err := core.ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	expectedFolder := filepath.Dir(connector.SessionPath(chat, "placeholder"))
	out := captureStdout(func() {
		if rc := Main([]string{"import", in}); rc != 0 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(out, "folder: "+expectedFolder) {
		t.Fatalf("stdout = %q", out)
	}
	if !strings.Contains(out, "resume: claude --resume") {
		t.Fatalf("stdout = %q", out)
	}
}

func TestLsListsLocalID(t *testing.T) {
	newCLIBase(t)
	chat, err := core.ChatCWD()
	if err != nil {
		t.Fatal(err)
	}
	if _, err := connector.WriteText(connector.SessionPath(chat, "only-one"), `{"uuid":"x"}`+"\n"); err != nil {
		t.Fatal(err)
	}
	out := captureStdout(func() {
		if rc := Main([]string{"ls"}); rc != 0 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if strings.TrimSpace(out) != "1. untitled" {
		t.Fatalf("stdout = %q", out)
	}
}

func TestUnknownCommandExits1(t *testing.T) {
	errOut := captureStderr(func() {
		if rc := Main([]string{"nope"}); rc != 1 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(errOut, "ferry:") {
		t.Fatalf("stderr = %q", errOut)
	}
}

func TestExportMissingNameExits1(t *testing.T) {
	errOut := captureStderr(func() {
		if rc := Main([]string{"export"}); rc != 1 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(errOut, "name required") {
		t.Fatalf("stderr = %q", errOut)
	}
}

func TestImportOpenUsesRunClaude(t *testing.T) {
	b := newCLIBase(t)
	in := filepath.Join(b.tmp, "in.jsonl")
	if err := os.WriteFile(in, []byte(`{"uuid":"u1","cwd":"/a","sessionId":"s"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	var called string
	old := runClaude
	runClaude = func(id string) error {
		called = id
		return nil
	}
	t.Cleanup(func() { runClaude = old })
	if rc := Main([]string{"import", in, "-o"}); rc != 0 {
		t.Fatalf("rc = %d", rc)
	}
	if called == "" {
		t.Fatal("runClaude not called")
	}
}

func TestImportOpenClaudeMissingStillSucceeds(t *testing.T) {
	b := newCLIBase(t)
	in := filepath.Join(b.tmp, "in.jsonl")
	if err := os.WriteFile(in, []byte(`{"uuid":"u1","cwd":"/a","sessionId":"s"}`+"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	old := runClaude
	runClaude = func(string) error { return os.ErrNotExist }
	t.Cleanup(func() { runClaude = old })
	errOut := captureStderr(func() {
		if rc := Main([]string{"import", in, "-o"}); rc != 0 {
			t.Fatalf("rc = %d", rc)
		}
	})
	if !strings.Contains(errOut, "'claude' not found on PATH") {
		t.Fatalf("stderr = %q", errOut)
	}
}
