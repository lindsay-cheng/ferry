package connector

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

type connectorBase struct {
	t      *testing.T
	config string
}

func newConnectorBase(t *testing.T) *connectorBase {
	t.Helper()
	dir := t.TempDir()
	t.Setenv("CLAUDE_CONFIG_DIR", dir)
	return &connectorBase{t: t, config: dir}
}

func (b *connectorBase) root() string {
	return filepath.Join(b.config, "projects")
}

func (b *connectorBase) make(encodedDir, sessionID, text string) string {
	if text == "" {
		text = "{}\n"
	}
	d := filepath.Join(b.root(), encodedDir)
	if err := os.MkdirAll(d, 0o755); err != nil {
		b.t.Fatal(err)
	}
	f := filepath.Join(d, sessionID+".jsonl")
	if err := os.WriteFile(f, []byte(text), 0o644); err != nil {
		b.t.Fatal(err)
	}
	return f
}

func TestProjectsRootUsesConfigDirEnv(t *testing.T) {
	b := newConnectorBase(t)
	want := filepath.Join(b.config, "projects")
	if got := ProjectsRoot(); got != want {
		t.Fatalf("ProjectsRoot() = %q, want %q", got, want)
	}
}

func TestProjectsRootDefaultsToHomeWithoutEnv(t *testing.T) {
	home, err := os.UserHomeDir()
	if err != nil {
		t.Fatal(err)
	}
	t.Setenv("CLAUDE_CONFIG_DIR", "")
	want := filepath.Join(home, ".claude", "projects")
	if got := ProjectsRoot(); got != want {
		t.Fatalf("ProjectsRoot() = %q, want %q", got, want)
	}
}

func TestEncodeCWDReplacesNonAlphanumeric(t *testing.T) {
	if got := EncodeCWD("/Users/bob/myapp"); got != "-Users-bob-myapp" {
		t.Fatalf("EncodeCWD bob = %q", got)
	}
	if got := EncodeCWD("/Users/me/proj.test_v2"); got != "-Users-me-proj-test-v2" {
		t.Fatalf("EncodeCWD proj.test_v2 = %q", got)
	}
}

func TestSessionPathComposition(t *testing.T) {
	b := newConnectorBase(t)
	want := filepath.Join(b.config, "projects", "-Users-bob-myapp", "abc-123.jsonl")
	if got := SessionPath("/Users/bob/myapp", "abc-123"); got != want {
		t.Fatalf("SessionPath() = %q, want %q", got, want)
	}
}

func TestErrorsAreComparable(t *testing.T) {
	if !errors.Is(fmtSessionNotFound(), ErrSessionNotFound) {
		t.Fatal("expected ErrSessionNotFound")
	}
	if !errors.Is(fmtAmbiguous(), ErrAmbiguousSession) {
		t.Fatal("expected ErrAmbiguousSession")
	}
}

func fmtSessionNotFound() error {
	return fmt.Errorf("%w: no session with id %q", ErrSessionNotFound, "x")
}

func fmtAmbiguous() error {
	return fmt.Errorf("%w: session id %q found in 2 project dirs: a, b", ErrAmbiguousSession, "dup")
}

func TestResolveNoneWhenAbsent(t *testing.T) {
	newConnectorBase(t)
	path, err := Resolve("missing-id")
	if err != nil {
		t.Fatal(err)
	}
	if path != "" {
		t.Fatalf("Resolve() = %q, want empty", path)
	}
}

func TestResolveSingleMatch(t *testing.T) {
	b := newConnectorBase(t)
	f := b.make("-Users-a-proj", "sess1", "{}\n")
	path, err := Resolve("sess1")
	if err != nil {
		t.Fatal(err)
	}
	if path != f {
		t.Fatalf("Resolve() = %q, want %q", path, f)
	}
}

func TestResolveAmbiguousRaises(t *testing.T) {
	b := newConnectorBase(t)
	b.make("-Users-a-proj", "dup", "{}\n")
	b.make("-Users-b-proj", "dup", "{}\n")
	_, err := Resolve("dup")
	if !errors.Is(err, ErrAmbiguousSession) {
		t.Fatalf("Resolve() err = %v, want ErrAmbiguousSession", err)
	}
}

func TestListSessionsEnumeratesAcrossDirs(t *testing.T) {
	b := newConnectorBase(t)
	f1 := b.make("-Users-a-proj", "s1", "{}\n")
	f2 := b.make("-Users-b-proj", "s2", "{}\n")
	got, err := ListSessions()
	if err != nil {
		t.Fatal(err)
	}
	want := []Session{{ID: "s1", Path: f1}, {ID: "s2", Path: f2}}
	if len(got) != len(want) {
		t.Fatalf("ListSessions() len = %d, want %d", len(got), len(want))
	}
	for i := range want {
		if got[i].ID != want[i].ID || got[i].Path != want[i].Path {
			t.Fatalf("ListSessions()[%d] = %+v, want %+v", i, got[i], want[i])
		}
	}
}

func TestListSessionsEmptyWhenNoRoot(t *testing.T) {
	newConnectorBase(t)
	got, err := ListSessions()
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Fatalf("ListSessions() = %+v, want empty", got)
	}
}

func TestListForCWDScopedToProject(t *testing.T) {
	b := newConnectorBase(t)
	cwd := "/Users/me/proj"
	f1 := b.make(EncodeCWD(cwd), "mine", "{}\n")
	b.make(EncodeCWD("/Users/me/other"), "theirs", "{}\n")
	got, err := ListForCWD(cwd)
	if err != nil {
		t.Fatal(err)
	}
	want := []Session{{ID: "mine", Path: f1}}
	if len(got) != 1 || got[0].ID != want[0].ID || got[0].Path != want[0].Path {
		t.Fatalf("ListForCWD() = %+v, want %+v", got, want)
	}
}

func TestListForCWDEmptyWhenNoSessions(t *testing.T) {
	newConnectorBase(t)
	got, err := ListForCWD("/Users/me/empty")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 0 {
		t.Fatalf("ListForCWD() = %+v, want empty", got)
	}
}

func TestReadTextByID(t *testing.T) {
	b := newConnectorBase(t)
	b.make("-Users-a-proj", "sid", `{"a":1}`+"\n")
	got, err := ReadText("sid")
	if err != nil {
		t.Fatal(err)
	}
	if got != `{"a":1}`+"\n" {
		t.Fatalf("ReadText() = %q", got)
	}
}

func TestReadTextByPath(t *testing.T) {
	b := newConnectorBase(t)
	f := b.make("-Users-a-proj", "sid", "LINE1\nLINE2\n")
	got, err := ReadText(f)
	if err != nil {
		t.Fatal(err)
	}
	if got != "LINE1\nLINE2\n" {
		t.Fatalf("ReadText() = %q", got)
	}
}

func TestReadTextMissingIDRaises(t *testing.T) {
	newConnectorBase(t)
	_, err := ReadText("nope")
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("ReadText() err = %v, want ErrSessionNotFound", err)
	}
}

func TestReadTextMissingPathRaises(t *testing.T) {
	b := newConnectorBase(t)
	missing := filepath.Join(b.root(), "-x", "no.jsonl")
	_, err := ReadText(missing)
	if !errors.Is(err, ErrSessionNotFound) {
		t.Fatalf("ReadText() err = %v, want ErrSessionNotFound", err)
	}
}

func TestReadTextAmbiguousIDPropagates(t *testing.T) {
	b := newConnectorBase(t)
	b.make("-Users-a-proj", "dup", "{}\n")
	b.make("-Users-b-proj", "dup", "{}\n")
	_, err := ReadText("dup")
	if !errors.Is(err, ErrAmbiguousSession) {
		t.Fatalf("ReadText() err = %v, want ErrAmbiguousSession", err)
	}
}

func TestWriteCreatesParentsAndWrites(t *testing.T) {
	b := newConnectorBase(t)
	p := filepath.Join(b.root(), "-Users-a-proj", "new.jsonl")
	ret, err := WriteText(p, "HELLO\n")
	if err != nil {
		t.Fatal(err)
	}
	if ret != p {
		t.Fatalf("WriteText() = %q, want %q", ret, p)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "HELLO\n" {
		t.Fatalf("file = %q", string(data))
	}
}

func TestWriteOverwritesUnconditionally(t *testing.T) {
	b := newConnectorBase(t)
	p := filepath.Join(b.root(), "-d", "s.jsonl")
	if _, err := WriteText(p, "first"); err != nil {
		t.Fatal(err)
	}
	if _, err := WriteText(p, "second"); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "second" {
		t.Fatalf("file = %q", string(data))
	}
}

func TestWriteIsByteFaithfulNoTrailingNewline(t *testing.T) {
	b := newConnectorBase(t)
	p := filepath.Join(b.root(), "-d", "s.jsonl")
	if _, err := WriteText(p, "no-newline"); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "no-newline" {
		t.Fatalf("file = %q", string(data))
	}
}

func TestWriteLeavesNoTempFiles(t *testing.T) {
	b := newConnectorBase(t)
	p := filepath.Join(b.root(), "-d", "s.jsonl")
	if _, err := WriteText(p, "x"); err != nil {
		t.Fatal(err)
	}
	entries, err := os.ReadDir(filepath.Dir(p))
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].Name() != "s.jsonl" {
		names := make([]string, len(entries))
		for i, e := range entries {
			names[i] = e.Name()
		}
		t.Fatalf("dir entries = %v, want [s.jsonl]", names)
	}
}

func TestWriteAcceptsStrPath(t *testing.T) {
	b := newConnectorBase(t)
	p := filepath.Join(b.root(), "-d", "s.jsonl")
	ret, err := WriteText(p, "y")
	if err != nil {
		t.Fatal(err)
	}
	if ret != p {
		t.Fatalf("WriteText() = %q, want %q", ret, p)
	}
	data, err := os.ReadFile(p)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "y" {
		t.Fatalf("file = %q", string(data))
	}
}
