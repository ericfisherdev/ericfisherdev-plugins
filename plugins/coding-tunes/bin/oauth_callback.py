#!/usr/bin/env python3
"""Waits for one OAuth redirect on 127.0.0.1 and prints its code.

Usage: oauth_callback.py <port> <state> <timeout-seconds>

Exit codes: 0 code printed, 1 denied or state mismatch, 2 timed out.
"""
import http.server
import sys
import urllib.parse

DENIED = 1
TIMED_OUT = 2


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    result = None

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
        is_valid = code is not None and state == self.server.expected_state
        CallbackHandler.result = code if is_valid else ""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        message = "Coding Tunes is linked. You can close this tab." if is_valid else "Login failed."
        self.wfile.write(message.encode())

    def log_message(self, *args):
        pass


def main(argv):
    port, state, timeout = int(argv[1]), argv[2], float(argv[3])
    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.expected_state = state
    server.timeout = timeout
    server.handle_request()
    if CallbackHandler.result is None:
        return TIMED_OUT
    if not CallbackHandler.result:
        return DENIED
    print(CallbackHandler.result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
