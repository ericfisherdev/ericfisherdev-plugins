"""The watcher ledger (ledger.json) and the single-poller lock.

Writers take a short lock file next to the ledger, re-read the data under it, and replace the
file atomically, so the poller and `report.py` never overwrite each other. Nothing slow may run
inside `update`: the lock is held for milliseconds and is broken after WRITER_LOCK_STALE_SECONDS.
"""

import contextlib
import copy
import json
import os
import time
import uuid

from config import retry_on_permission_error, write_json_atomic
from gh_client import load_state

WRITER_LOCK_STALE_SECONDS = 30
# The poller heartbeats after every scan, event and dispatch, so a healthy poller must stay fresh
# for longer than the slowest single step: one scan plus one dispatch (tab launch and relay call).
SCAN_TIMEOUT_SECONDS = 600
POLLER_STALE_SECONDS = 1200
SECTIONS = ("seen", "active", "done")


class LedgerBusy(Exception):
    pass


class PollerRunning(Exception):
    def __init__(self, pid, age):
        super().__init__(f"another poller (pid {pid}) heartbeat {int(age)}s ago")
        self.pid = pid
        self.age = age


def empty():
    return {section: {} for section in SECTIONS}


def normalise(data):
    """`seen` maps owner/name#N to the newest activity dispatched; `active` and `done` hold sessions."""
    for section in SECTIONS:
        if not isinstance(data.get(section), dict):
            data[section] = {}
    return data


def read(path):
    return normalise(load_state(str(path)))


def write_atomic(path, data, replace=os.replace, sleep=time.sleep):
    write_json_atomic(path, data, ".ledger-", replace=replace, sleep=sleep)


def _lock_state(path):
    """(token, mtime_ns) of a writer lock, or None when it is gone. An unreadable body has token None."""
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = None
    return (data.get("token") if isinstance(data, dict) else None, mtime)


def _remove_if(lock, matches):
    """Remove the writer lock only if `matches(state)`; True when removed.

    A lock unlinked by name can be a newer writer's, created after we looked. Renaming first takes
    exactly one file out of the way, and a file that turns out not to be the one we meant is linked
    back. The link-back fails rather than overwrite a lock a third writer created in between; that
    writer and the one whose lock was moved then both believe they hold it, so this narrows the race
    to the moment between rename and link without closing it.
    """
    grave = f"{lock}.{uuid.uuid4().hex}.grave"
    try:
        retry_on_permission_error(lambda: os.rename(lock, grave))
    except OSError:
        return False
    removed = matches(_lock_state(grave))
    if not removed:
        with contextlib.suppress(OSError):
            os.link(grave, lock)
    with contextlib.suppress(OSError):
        os.unlink(grave)
    return removed


def _take_writer_lock(lock, timeout, clock, sleep):
    """Take the writer lock and return its token."""
    deadline = clock() + timeout
    token = uuid.uuid4().hex
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # Age and identity come from one reading, so a lock replaced after it was judged
            # stale no longer matches and is left alone.
            observed = _lock_state(lock)
            if observed is None:
                continue
            if clock() - observed[1] / 1e9 > WRITER_LOCK_STALE_SECONDS:
                if _remove_if(lock, lambda state, seen=observed: state == seen):
                    continue
            if clock() >= deadline:
                raise LedgerBusy(f"ledger is locked ({lock}); another writer is active")
            sleep(0.05)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "at": clock(), "token": token}, fh)
        return token


@contextlib.contextmanager
def update(path, timeout=15, clock=time.time, sleep=time.sleep):
    """Lock, yield the normalised ledger, and write it back if the block does not raise."""
    path = str(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    lock = path + ".lock"
    token = _take_writer_lock(lock, timeout, clock, sleep)
    try:
        data = read(path)
        yield data
        write_atomic(path, data)
    finally:
        _remove_if(lock, lambda state: state is not None and state[0] == token)


@contextlib.contextmanager
def snapshot(path):
    """A deep copy of the ledger that is never written back."""
    yield copy.deepcopy(read(path))


def _read_poller(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _create_poller(path, token, now):
    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(dict(token, heartbeat_at=now), fh)


def acquire_poller(path, now=None, stale=POLLER_STALE_SECONDS, pid=None):
    """Take poller.lock and return its token; raise PollerRunning when a fresh one exists."""
    now = time.time() if now is None else now
    token = {"pid": os.getpid() if pid is None else pid, "started_at": now}
    path = str(path)
    existing = _read_poller(path) if os.path.exists(path) else None
    if os.path.exists(path):
        beat = existing.get("heartbeat_at") if existing else None
        if isinstance(beat, (int, float)) and now - beat < stale:
            raise PollerRunning(existing.get("pid"), now - beat)
        with contextlib.suppress(OSError):
            os.unlink(path)
    try:
        _create_poller(path, token, now)
    except FileExistsError:
        other = _read_poller(path) or {}
        raise PollerRunning(other.get("pid"), 0)
    return token


def _ours(data, token):
    return bool(data) and data.get("pid") == token["pid"] and data.get("started_at") == token["started_at"]


def heartbeat(path, token, now=None):
    """Refresh our lock; False when it has been taken over or removed."""
    now = time.time() if now is None else now
    data = _read_poller(str(path))
    if not _ours(data, token):
        return False
    data["heartbeat_at"] = now
    write_atomic(path, data)
    return True


def release(path, token):
    """Remove poller.lock only if it is ours."""
    if _ours(_read_poller(str(path)), token):
        with contextlib.suppress(OSError):
            os.unlink(str(path))
