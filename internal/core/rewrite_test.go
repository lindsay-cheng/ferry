package core

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testdata(t *testing.T, name string) string {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("..", "..", "testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

func parseLines(t *testing.T, text string) []map[string]any {
	t.Helper()
	var out []map[string]any
	for _, line := range strings.Split(text, "\n") {
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

func TestRewriteLineUserFixture(t *testing.T) {
	raw := strings.TrimSpace(testdata(t, "user.jsonl"))
	const newID = "new-sess-1"
	const cwd = "/tmp/ferry-test"

	got, err := RewriteLine(raw, newID, cwd)
	if err != nil {
		t.Fatal(err)
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(strings.TrimSpace(got)), &obj); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"parentUuid", "type", "uuid", "timestamp", "message"} {
		if _, ok := obj[key]; !ok {
			t.Fatalf("missing key %q", key)
		}
	}
	if obj["cwd"] != cwd {
		t.Fatalf("cwd = %v, want %q", obj["cwd"], cwd)
	}
	if obj["sessionId"] != newID {
		t.Fatalf("sessionId = %v, want %q", obj["sessionId"], newID)
	}
}

func TestRewriteLineInvalidJSON(t *testing.T) {
	_, err := RewriteLine(`{"truncated":`, "id", "/cwd")
	if err != ErrInvalidJSON {
		t.Fatalf("err = %v, want ErrInvalidJSON", err)
	}
}

func TestRewriteTextExtraTypesFixture(t *testing.T) {
	text := testdata(t, "extra-types.jsonl")
	const newID = "imported-id"
	const cwd = "/Users/bob/work"

	out, warns, err := RewriteText(text, newID, cwd, "import")
	if err != nil {
		t.Fatal(err)
	}
	if len(warns) != 0 {
		t.Fatalf("warns = %v, want none", warns)
	}
	entries := parseLines(t, out)
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

func TestRewriteTextTruncatedFixture(t *testing.T) {
	text := testdata(t, "truncated.jsonl")
	const newID = "after-trunc"
	const cwd = "/tmp/cwd"

	out, warns, err := RewriteText(text, newID, cwd, "session 'auth'")
	if err != nil {
		t.Fatal(err)
	}
	if len(warns) != 1 || !strings.Contains(warns[0], "skipping invalid JSON on last line") {
		t.Fatalf("warns = %v, want one last-line skip warning", warns)
	}
	lines := strings.Split(strings.TrimRight(out, "\n"), "\n")
	if len(lines) != 1 {
		t.Fatalf("got %d lines, want 1", len(lines))
	}
	var obj map[string]any
	if err := json.Unmarshal([]byte(lines[0]), &obj); err != nil {
		t.Fatal(err)
	}
	if obj["cwd"] != cwd || obj["sessionId"] != newID {
		t.Fatalf("rewrite mismatch: cwd=%v sessionId=%v", obj["cwd"], obj["sessionId"])
	}
}

func TestRewriteTextEmptyHistory(t *testing.T) {
	_, _, err := RewriteText("\n\n", "id", "/cwd", "import")
	if err != ErrNoHistory {
		t.Fatalf("err = %v, want ErrNoHistory", err)
	}
}
