"""Fakes and fixtures shared by the unit tests. Nothing here touches GitHub or a real repository."""

import json

HEAD = "a" * 40
OLD = "b" * 40

DIFF = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,4 +10,5 @@ def handler():
     a = 1
-    b = 2
+    b = 3
+    c = 4
     return a
@@ -40,2 +41,3 @@ def other():
     x = 1
+    y = 2
     return x
diff --git a/db/migrations/001.sql b/db/migrations/001.sql
new file mode 100644
index 0000000..3333333
--- /dev/null
+++ b/db/migrations/001.sql
@@ -0,0 +1,2 @@
+CREATE TABLE t (id INT);
+CREATE INDEX i ON t (id);
diff --git a/old/gone.py b/old/gone.py
deleted file mode 100644
index 4444444..0000000
--- a/old/gone.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def gone():
-    pass
-
diff --git a/package-lock.json b/package-lock.json
index 5555555..6666666 100644
--- a/package-lock.json
+++ b/package-lock.json
@@ -1,1 +1,1 @@
-{"v": 1}
+{"v": 2}
diff --git a/lib/a.py b/lib/b.py
similarity index 90%
rename from lib/a.py
rename to lib/b.py
index 7777777..8888888 100644
--- a/lib/a.py
+++ b/lib/b.py
@@ -1,2 +1,2 @@
-old = 1
+new = 1
 keep = 2
"""


def pr_meta(**overrides):
    meta = {"number": 7, "title": "Add the thing", "body": "Does the thing.", "author": {"login": "author"},
            "state": "OPEN", "isDraft": False, "baseRefName": "main", "headRefName": "feature", "headRefOid": HEAD,
            "additions": 6, "deletions": 5, "changedFiles": 5, "url": "https://example.test/pr/7",
            "reviewDecision": ""}
    meta.update(overrides)
    return meta


class FakeRunner:
    """Matches a command by substrings of its joined argv and records every call."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, match, stdout="", rc=0, stderr=""):
        if isinstance(match, str):
            match = [match]
        if not isinstance(stdout, str):
            stdout = json.dumps(stdout)
        self.routes.append((match, rc, stdout, stderr))
        return self

    def __call__(self, argv, cwd=None):
        joined = " ".join(argv)
        self.calls.append(joined)
        for match, rc, stdout, stderr in self.routes:
            if all(part in joined for part in match):
                return rc, stdout, stderr
        raise AssertionError(f"unexpected command: {joined}")

    def count(self, fragment):
        return sum(1 for joined in self.calls if fragment in joined)
