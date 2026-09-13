"""In-memory fake of the supabase-py client, for tests.

Implements just the chainable query-builder surface that weave.remote uses:

    client.table(name).upsert(payload, on_conflict="a,b").execute()
    client.table(name).select("cols").eq(col, val)...[.limit(n)].execute()

`.execute()` returns an object with a `.data` list, mirroring supabase-py.
Rows live in a single shared list so upserts and selects see the same state.
"""


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store):
        self._store = store
        self._op = None
        self._filters = []
        self._limit = None

    def upsert(self, payload, on_conflict=None):
        self._op = ("upsert", dict(payload), on_conflict)
        return self

    def select(self, cols):
        self._op = ("select", cols)
        return self

    def delete(self):
        self._op = ("delete",)
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        kind = self._op[0]
        if kind == "upsert":
            return self._execute_upsert()
        if kind == "delete":
            return self._execute_delete()
        return self._execute_select()

    def _execute_delete(self):
        matched = list(self._store)
        for col, val in self._filters:
            matched = [r for r in matched if r.get(col) == val]
        for row in matched:
            self._store.remove(row)
        return _Result([dict(r) for r in matched])

    def _execute_upsert(self):
        _, payload, on_conflict = self._op
        keys = [k.strip() for k in (on_conflict or "").split(",") if k.strip()]
        for row in self._store:
            if keys and all(row.get(k) == payload.get(k) for k in keys):
                row.update(payload)
                return _Result([dict(row)])
        new_row = dict(payload)
        self._store.append(new_row)
        return _Result([dict(new_row)])

    def _execute_select(self):
        rows = list(self._store)
        for col, val in self._filters:
            rows = [r for r in rows if r.get(col) == val]
        if self._limit is not None:
            rows = rows[: self._limit]
        cols = self._op[1]
        if cols in (None, "*"):
            return _Result([dict(r) for r in rows])
        wanted = [c.strip() for c in cols.split(",")]
        return _Result([{k: r.get(k) for k in wanted} for r in rows])


class FakeSupabaseClient:
    def __init__(self):
        self.store = []  # list of row dicts

    def table(self, name):  # noqa: ARG002 - single-table fake
        return _Query(self.store)
