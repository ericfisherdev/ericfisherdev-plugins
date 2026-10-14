#!/usr/bin/env python3
"""Talks to the one shared mpv over its JSON IPC socket.

Usage: mpvctl.py <socket> <command> [argument]

Commands:
  ensure <url> [cookies]  start mpv paused on <url>, or load <url> into the
                running one; [cookies] is yt-dlp's --cookies-from-browser value
  play | pause | next | prev | quit
  status        print {"track", "isPlaying", "elapsedSeconds"} as JSON

Exit codes: 0 ok, 2 mpv not running, 3 mpv or yt-dlp missing, 4 bad usage,
5 mpv is running but busy (it does not answer while yt-dlp loads a playlist).
"""
import json
import shutil
import socket
import subprocess
import sys
import time

NOT_RUNNING = 2
MISSING_DEPENDENCY = 3
BAD_USAGE = 4
BUSY = 5

UP, BUSY_STATE, DOWN = "up", "busy", "down"
# How long one probe waits for an answer before calling mpv busy.
PROBE_TIMEOUT_SECONDS = 1.0
# How long ensure waits for a busy mpv to answer. The hook kills ensure after
# 20 s including the start lock wait, so a session queued behind another may be
# cut short; that only reports a load failure, it never starts a second mpv.
RESPONSIVE_WAIT_SECONDS = 12.0
# How long a play/pause/next/prev/status waits for a busy mpv.
COMMAND_WAIT_SECONDS = 3.0
# How long a fresh mpv may take to open its socket.
SOCKET_OPEN_SECONDS = 5.0


def send(sock_path, command, timeout=3):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(timeout)
        conn.connect(sock_path)
        conn.sendall((json.dumps({"command": command, "request_id": 1}) + "\n").encode())
        buffer = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                raise ConnectionError("mpv closed the socket")
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                reply = json.loads(line or b"{}")
                if reply.get("request_id") == 1:
                    return reply


def probe(sock_path):
    """UP answers; BUSY_STATE accepts the connection but does not answer in
    time, as mpv does while yt-dlp loads; DOWN has no socket or no listener."""
    try:
        send(sock_path, ["get_property", "pid"], PROBE_TIMEOUT_SECONDS)
        return UP
    except socket.timeout:
        return BUSY_STATE
    except (OSError, ConnectionError, ValueError):
        return DOWN


def wait_until_answering(sock_path, seconds):
    """UP or DOWN as soon as either is seen; BUSY_STATE if mpv is still busy at the deadline."""
    deadline = time.monotonic() + seconds
    while True:
        state = probe(sock_path)
        if state != BUSY_STATE or time.monotonic() >= deadline:
            return state
        time.sleep(0.1)


def source_path(sock_path):
    return f"{sock_path}.source.json"


def loaded_source(sock_path):
    """The (url, cookies) mpv was last started or loaded with, kept in a file
    beside the socket so a load still running when ensure gave up is not redone."""
    try:
        with open(source_path(sock_path)) as source:
            data = json.load(source)
        return data["url"], data["cookies"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_source(sock_path, url, cookies):
    with open(source_path(sock_path), "w") as source:
        json.dump({"url": url, "cookies": cookies}, source)


def get(sock_path, name):
    reply = send(sock_path, ["get_property", name])
    return reply.get("data") if reply.get("error") == "success" else None


def raw_options(cookies):
    return {"cookies-from-browser": cookies} if cookies else {}


def start(sock_path, url, cookies):
    for tool in ("mpv", "yt-dlp"):
        if shutil.which(tool) is None:
            print(f"{tool} is not installed", file=sys.stderr)
            sys.exit(MISSING_DEPENDENCY)
    record_source(sock_path, url, cookies)
    subprocess.Popen(
        [
            "mpv", "--no-video", "--no-terminal", "--pause", "--idle=yes",
            "--loop-playlist=inf", "--ytdl-format=bestaudio/best",
            f"--input-ipc-server={sock_path}",
            *([f"--ytdl-raw-options-append=cookies-from-browser={cookies}"] if cookies else []),
            url,
        ],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    # A socket that accepts counts as started, even before mpv answers on it.
    deadline = time.monotonic() + SOCKET_OPEN_SECONDS
    while probe(sock_path) == DOWN:
        if time.monotonic() >= deadline:
            print("mpv did not open its socket", file=sys.stderr)
            sys.exit(NOT_RUNNING)
        time.sleep(0.1)


def has_failed(sock_path):
    # Idle with entries queued means the playlist URL failed to open.
    return get(sock_path, "idle-active") is True and (get(sock_path, "playlist-count") or 0) > 0


def ensure(sock_path, url, cookies):
    # Only a missing listener starts mpv: a busy one is still the shared player,
    # and a second mpv would take over the socket and orphan it.
    started = probe(sock_path) == DOWN
    if started:
        start(sock_path, url, cookies)
    state = wait_until_answering(sock_path, RESPONSIVE_WAIT_SECONDS)
    if state == DOWN:
        print("mpv exited before it answered", file=sys.stderr)
        sys.exit(NOT_RUNNING)
    if state == BUSY_STATE:
        print("mpv is busy loading; try again shortly", file=sys.stderr)
        sys.exit(BUSY)
    # A fresh mpv's failure is left to the hook's status check and its retry wait.
    if (not started and has_failed(sock_path)) or loaded_source(sock_path) != (url, cookies):
        record_source(sock_path, url, cookies)
        send(sock_path, ["set_property", "ytdl-raw-options", raw_options(cookies)])
        send(sock_path, ["loadfile", url, "replace"])
        send(sock_path, ["set_property", "pause", True])


def status(sock_path):
    elapsed = get(sock_path, "time-pos")
    print(json.dumps({
        "track": get(sock_path, "media-title") or "",
        "isPlaying": get(sock_path, "pause") is False,
        "elapsedSeconds": int(elapsed) if isinstance(elapsed, (int, float)) else None,
        "hasFailed": has_failed(sock_path),
    }))


SIMPLE = {
    "play": ["set_property", "pause", False],
    "pause": ["set_property", "pause", True],
    "next": ["playlist-next", "force"],
    "prev": ["playlist-prev", "force"],
    "quit": ["quit"],
}


def main(argv):
    if len(argv) < 3:
        print(__doc__, file=sys.stderr)
        return BAD_USAGE
    sock_path, command = argv[1], argv[2]
    if command == "ensure" and len(argv) in (4, 5):
        ensure(sock_path, argv[3], argv[4] if len(argv) == 5 else "")
        return 0
    if command not in SIMPLE and command != "status":
        print(__doc__, file=sys.stderr)
        return BAD_USAGE
    state = wait_until_answering(sock_path, COMMAND_WAIT_SECONDS)
    if state == DOWN:
        return NOT_RUNNING
    if state == BUSY_STATE:
        if command == "quit":
            # Best effort and unverified against mpv: the quit may only take
            # effect if mpv reads it before this connection closes.
            try:
                send(sock_path, SIMPLE["quit"], PROBE_TIMEOUT_SECONDS)
            except (OSError, ConnectionError, ValueError):
                pass
        return BUSY
    if command == "status":
        status(sock_path)
    else:
        send(sock_path, SIMPLE[command])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
