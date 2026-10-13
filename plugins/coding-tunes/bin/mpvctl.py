#!/usr/bin/env python3
"""Talks to the one shared mpv over its JSON IPC socket.

Usage: mpvctl.py <socket> <command> [argument]

Commands:
  ensure <url> [cookies]  start mpv paused on <url>, or load <url> into the
                running one; [cookies] is yt-dlp's --cookies-from-browser value
  play | pause | next | prev | quit
  status        print {"track", "isPlaying", "elapsedSeconds"} as JSON

Exit codes: 0 ok, 2 mpv not running, 3 mpv or yt-dlp missing, 4 bad usage.
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


def send(sock_path, command):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
        conn.settimeout(3)
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


def is_running(sock_path):
    try:
        send(sock_path, ["get_property", "pid"])
        return True
    except (OSError, ConnectionError, ValueError):
        return False


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
    for _ in range(50):
        if is_running(sock_path):
            return
        time.sleep(0.1)
    print("mpv did not open its socket", file=sys.stderr)
    sys.exit(NOT_RUNNING)


def has_failed(sock_path):
    # Idle with entries queued means the playlist URL failed to open.
    return get(sock_path, "idle-active") is True and (get(sock_path, "playlist-count") or 0) > 0


def ensure(sock_path, url, cookies):
    if not is_running(sock_path):
        start(sock_path, url, cookies)
    elif has_failed(sock_path) or (
        get(sock_path, "user-data/coding-tunes/url"), get(sock_path, "user-data/coding-tunes/cookies")
    ) != (url, cookies):
        send(sock_path, ["set_property", "ytdl-raw-options", raw_options(cookies)])
        send(sock_path, ["loadfile", url, "replace"])
        send(sock_path, ["set_property", "pause", True])
    send(sock_path, ["set_property", "user-data/coding-tunes/url", url])
    send(sock_path, ["set_property", "user-data/coding-tunes/cookies", cookies])


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
    if not is_running(sock_path):
        return NOT_RUNNING
    if command == "status":
        status(sock_path)
    else:
        send(sock_path, SIMPLE[command])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
