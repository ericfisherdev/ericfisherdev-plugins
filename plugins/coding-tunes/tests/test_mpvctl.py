"""Tests for bin/mpvctl.py against a fake mpv on PATH.

Run: python3 -m unittest discover -s plugins/coding-tunes/tests -p 'test_*.py'
"""
import importlib.util
import json
import os
import socket
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "mpvctl.py"

# Answers mpv's JSON IPC on --input-ipc-server, logging "started" and every
# command it receives. For FAKE_MPV_BUSY_SECONDS after start it accepts
# connections but never answers, as mpv does while yt-dlp loads a playlist.
FAKE_MPV = r'''#!/usr/bin/env python3
import json, os, socket, sys, time
sock_path = next(a.split("=", 1)[1] for a in sys.argv if a.startswith("--input-ipc-server="))
log_path = os.environ["FAKE_MPV_LOG"]
busy_until = time.monotonic() + float(os.environ.get("FAKE_MPV_BUSY_SECONDS", "0"))
def log(line):
    with open(log_path, "a") as out:
        out.write(line + "\n")
log("started")
if os.fork():
    sys.exit(0)
server = socket.socket(socket.AF_UNIX)
if os.path.exists(sock_path):
    os.unlink(sock_path)
server.bind(sock_path)
server.listen()
held = []
while True:
    conn, _ = server.accept()
    if time.monotonic() < busy_until:
        held.append(conn)
        continue
    for line in conn.makefile():
        request = json.loads(line)
        if request["command"][0] != "get_property":
            log(json.dumps(request["command"]))
        if request["command"] == ["quit"]:
            sys.exit(0)
        conn.sendall((json.dumps({"request_id": request["request_id"], "error": "success", "data": None}) + "\n").encode())
'''

URL = "https://example.test/list"


def load_mpvctl():
    spec = importlib.util.spec_from_file_location("mpvctl", BIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BusySocket:
    """An mpv that accepts IPC connections but never answers, as while it loads a playlist."""

    def __init__(self, path):
        self.server = socket.socket(socket.AF_UNIX)
        self.server.bind(path)
        self.server.listen()
        self.connections = []
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            self.connections.append(conn)

    def close(self):
        self.server.close()
        for conn in self.connections:
            conn.close()


class MpvctlTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.sock = str(root / "mpv.sock")
        self.log = root / "mpv.log"
        fake_bin = root / "bin"
        fake_bin.mkdir()
        for name, body in (("mpv", FAKE_MPV), ("yt-dlp", "#!/bin/sh\n")):
            path = fake_bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        env = {"PATH": f"{fake_bin}:{os.environ['PATH']}", "FAKE_MPV_LOG": str(self.log), "FAKE_MPV_BUSY_SECONDS": "0"}
        self.saved_env = {key: os.environ.get(key) for key in env}
        os.environ.update(env)
        self.mpvctl = load_mpvctl()
        self.mpvctl.RESPONSIVE_WAIT_SECONDS = 1.0
        self.mpvctl.COMMAND_WAIT_SECONDS = 1.0
        self.mpvctl.PROBE_TIMEOUT_SECONDS = 0.2

    def tearDown(self):
        deadline = time.monotonic() + 3
        while os.path.exists(self.sock) and time.monotonic() < deadline:
            try:
                self.mpvctl.send(self.sock, ["quit"], 0.5)
                break
            except socket.timeout:
                time.sleep(0.2)
            except (OSError, ConnectionError, ValueError):
                break
        for key, value in self.saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.dir.cleanup()

    def log_lines(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def starts(self):
        return self.log_lines().count("started")

    def loads(self):
        return [line for line in self.log_lines() if line.startswith('["loadfile"')]

    def test_should_start_mpv_when_no_socket_exists(self):
        self.mpvctl.ensure(self.sock, URL, "")

        self.assertEqual(self.starts(), 1)

    def test_should_not_reload_a_freshly_started_mpv(self):
        self.mpvctl.ensure(self.sock, URL, "")

        self.assertEqual(self.loads(), [])

    def test_should_not_start_or_reload_when_the_running_mpv_has_the_same_playlist(self):
        self.mpvctl.ensure(self.sock, URL, "")
        self.mpvctl.ensure(self.sock, URL, "")

        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.loads(), [])

    def test_should_load_a_different_playlist_into_the_running_mpv(self):
        self.mpvctl.ensure(self.sock, URL, "")
        self.mpvctl.ensure(self.sock, "https://example.test/other", "firefox")

        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.loads(), ['["loadfile", "https://example.test/other", "replace"]'])

    def test_should_not_start_a_second_mpv_while_the_running_one_is_busy(self):
        busy = BusySocket(self.sock)
        try:
            with self.assertRaises(SystemExit) as raised:
                self.mpvctl.ensure(self.sock, URL, "")
        finally:
            busy.close()

        self.assertEqual(raised.exception.code, self.mpvctl.BUSY)
        self.assertEqual(self.starts(), 0)

    def test_should_not_reload_a_playlist_whose_first_load_outlasted_the_wait(self):
        os.environ["FAKE_MPV_BUSY_SECONDS"] = "1.5"
        with self.assertRaises(SystemExit) as raised:
            self.mpvctl.ensure(self.sock, URL, "")
        self.assertEqual(raised.exception.code, self.mpvctl.BUSY)
        time.sleep(1.0)

        self.mpvctl.ensure(self.sock, URL, "")

        self.assertEqual(self.starts(), 1)
        self.assertEqual(self.loads(), [])

    def test_should_start_mpv_when_the_socket_file_is_stale(self):
        stale = socket.socket(socket.AF_UNIX)
        stale.bind(self.sock)
        stale.close()

        self.mpvctl.ensure(self.sock, URL, "")

        self.assertEqual(self.starts(), 1)

    def test_should_report_busy_not_stopped_for_a_command_while_mpv_is_busy(self):
        busy = BusySocket(self.sock)
        try:
            code = self.mpvctl.main(["mpvctl.py", self.sock, "play"])
        finally:
            busy.close()

        self.assertEqual(code, self.mpvctl.BUSY)

    def test_should_report_not_running_at_once_when_there_is_no_mpv(self):
        self.mpvctl.COMMAND_WAIT_SECONDS = 5.0
        began = time.monotonic()

        code = self.mpvctl.main(["mpvctl.py", self.sock, "pause"])

        self.assertEqual(code, self.mpvctl.NOT_RUNNING)
        self.assertLess(time.monotonic() - began, 1.0)


if __name__ == "__main__":
    unittest.main()
