"""Watcher events: printed in the watcher window and appended to the log."""

from datetime import datetime

# The only list of session outcomes: name -> meaning shown in the prompt.
OUTCOMES = {
    "posted": "review or replies were posted to GitHub",
    "skipped": "the workflow or the developer chose not to act",
    "no-op": "there was nothing to do",
    "failed": "the workflow hit an error and could not complete",
}


class Events:
    def __init__(self, log_path, out=print, now=datetime.now, dry_run=False):
        self.log_path = log_path
        self.out = out
        self.now = now
        self.dry_run = dry_run
        self.noted_start = False

    def _line(self, text):
        line = f"[{self.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}"
        self.out(line)
        if self.dry_run:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as err:
            self.out(f"could not write the log {self.log_path}: {err}")

    def start_note(self):
        if self.noted_start:
            return
        self.noted_start = True
        if self.dry_run:
            self._line("dry run: nothing is dispatched, recorded or logged")
        else:
            self._line(f"events go to this window and {self.log_path}")

    def note(self, text):
        self._line(text)

    def emit(self, event_type, **fields):
        target = fields.get("repo", "")
        if fields.get("pr") is not None:
            target = f"{target}#{fields['pr']}"
        detail = fields.get("summary") or ""
        if event_type == "stale-session" and fields.get("idle_minutes") is not None:
            detail = f"idle {fields['idle_minutes']} min"
        if fields.get("cwd"):
            detail = f"{detail} in {fields['cwd']}" if detail else f"in {fields['cwd']}"
        parts = [event_type, target, fields.get("session") or "", detail]
        self._line(" ".join(p for p in parts if p))
