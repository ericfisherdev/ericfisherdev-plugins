"""A fake gh runner for the unit tests. It matches calls by argument prefix and records every call."""

import json


class FakeGh:
    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, match, stdout="", rc=0, stderr=""):
        """Register a response for any call whose joined args contain every string in `match`."""
        if isinstance(match, str):
            match = [match]
        if not isinstance(stdout, str):
            stdout = json.dumps(stdout)
        self.routes.append((match, rc, stdout, stderr))
        return self

    def on_lines(self, match, items):
        """Register an NDJSON response, the shape `gh api --paginate --jq '.[]'` prints."""
        return self.on(match, "\n".join(json.dumps(i) for i in items) + ("\n" if items else ""))

    def __call__(self, args, input=None):
        joined = " ".join(args)
        self.calls.append((joined, input))
        for match, rc, stdout, stderr in self.routes:
            if all(m in joined for m in match):
                return rc, stdout, stderr
        raise AssertionError(f"unexpected gh call: {joined}")

    def count(self, fragment):
        return sum(1 for joined, _ in self.calls if fragment in joined)
