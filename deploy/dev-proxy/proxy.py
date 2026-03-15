#!/usr/bin/env python3
"""
Codex Dev Proxy — rewrites OpenAI 429 usage_limit_reached responses.

This is a DEVELOPMENT-ONLY tool. It sits between Codex and api.openai.com,
transparently forwarding all requests and responses, but intercepting any
429 response whose body contains "usage_limit_reached" and replacing it with
a synthetic "no models available" 503 that Codex treats as a retryable
ServerOverloaded error — so the session keeps running.

Usage:
    python3 proxy.py [--port 8080] [--upstream https://api.openai.com]

Then in ~/.codex/config.toml:
    openai_base_url = "http://127.0.0.1:8080/v1"

WARNING: This proxy forwards your OpenAI auth token to the upstream.
         Never expose it on a public interface.
"""

import argparse
import json
import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, urlunparse
import urllib.request
import urllib.error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("codex-dev-proxy")

UPSTREAM_DEFAULT = "https://api.openai.com"

# The JSON body OpenAI returns when the weekly limit is exhausted.
USAGE_LIMIT_ERROR_TYPE = "usage_limit_reached"

# What we replace it with:
#
# Codex's api_bridge.rs maps HTTP responses as follows:
#   429 + error_type=="usage_limit_reached" → CodexErr::UsageLimitReached  (NOT retryable)
#   429 (any other body)                    → CodexErr::RetryLimit          (NOT retryable)
#   503 + code=="server_is_overloaded"      → CodexErr::ServerOverloaded    (NOT retryable)
#   500                                     → CodexErr::InternalServerError  (IS retryable ✓)
#   other non-200                           → CodexErr::UnexpectedStatus     (IS retryable ✓)
#
# We rewrite to 500 so Codex treats it as a transient InternalServerError and retries.
SYNTHETIC_500_BODY = json.dumps({
    "error": {
        "code": "internal_server_error",
        "message": "[dev-proxy] Weekly limit intercepted — session continues (dev mode).",
        "type": "server_error",
    }
}).encode()


class ProxyHandler(BaseHTTPRequestHandler):
    upstream: str = UPSTREAM_DEFAULT

    def log_message(self, fmt, *args):
        # Suppress the default noisy per-request log; we do our own.
        pass

    def _forward(self):
        parsed = urlparse(self.upstream)
        target_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            self.path,
            "", "", ""
        ))

        # Read request body.
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else None

        # Build upstream request, forwarding all headers except Host.
        req_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "content-length")
        }
        if body:
            req_headers["Content-Length"] = str(len(body))

        req = urllib.request.Request(
            target_url,
            data=body,
            headers=req_headers,
            method=self.command,
        )

        try:
            with urllib.request.urlopen(req) as resp:
                resp_body = resp.read()
                self._send_response(resp.status, dict(resp.headers), resp_body)
        except urllib.error.HTTPError as e:
            resp_body = e.read()
            status = e.code

            # ── Intercept 429 usage_limit_reached ──────────────────────────
            if status == 429:
                try:
                    parsed_body = json.loads(resp_body)
                    error_type = (
                        parsed_body.get("error", {}).get("error_type")
                        or parsed_body.get("error", {}).get("type")
                    )
                    if error_type == USAGE_LIMIT_ERROR_TYPE:
                        log.warning(
                            "⚡ [dev-proxy] Intercepted 429 usage_limit_reached → "
                            "replacing with 500 InternalServerError (retryable)"
                        )
                        self._send_response(
                            500,
                            {"Content-Type": "application/json"},
                            SYNTHETIC_500_BODY,
                        )
                        return
                except (json.JSONDecodeError, AttributeError):
                    pass

            self._send_response(status, dict(e.headers), resp_body)

    def _send_response(self, status: int, headers: dict, body: bytes):
        self.send_response(status)
        skip = {"transfer-encoding", "connection", "content-encoding"}
        for k, v in headers.items():
            if k.lower() not in skip:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):    self._forward()
    def do_POST(self):   self._forward()
    def do_PUT(self):    self._forward()
    def do_DELETE(self): self._forward()
    def do_PATCH(self):  self._forward()
    def do_HEAD(self):   self._forward()
    def do_OPTIONS(self): self._forward()


def main():
    parser = argparse.ArgumentParser(description="Codex dev proxy")
    parser.add_argument("--port", type=int, default=8080,
                        help="Local port to listen on (default: 8080)")
    parser.add_argument("--upstream", default=UPSTREAM_DEFAULT,
                        help=f"Upstream API base URL (default: {UPSTREAM_DEFAULT})")
    args = parser.parse_args()

    ProxyHandler.upstream = args.upstream.rstrip("/")

    server = HTTPServer(("127.0.0.1", args.port), ProxyHandler)
    log.info("=" * 60)
    log.info("  Codex Dev Proxy — DEVELOPMENT USE ONLY")
    log.info("=" * 60)
    log.info(f"  Listening on : http://127.0.0.1:{args.port}")
    log.info(f"  Upstream     : {ProxyHandler.upstream}")
    log.info(f"  Intercepts   : 429 usage_limit_reached → 503 overloaded")
    log.info("")
    log.info("  Add to ~/.codex/config.toml:")
    log.info(f'    openai_base_url = "http://127.0.0.1:{args.port}/v1"')
    log.info("=" * 60)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Proxy stopped.")


if __name__ == "__main__":
    main()
