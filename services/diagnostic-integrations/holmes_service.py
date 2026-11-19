# SPDX-License-Identifier: AGPL-3.0-only
"""Internal-only credential-isolated Holmes service; do not publish its port."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

TOKEN = os.environ.get("HOLMES_SERVICE_TOKEN", "")


def concurrency_limit():
    try:
        value=int(os.environ.get('HOLMES_MAX_CONCURRENCY','4'))
    except ValueError:
        raise ValueError('HOLMES_MAX_CONCURRENCY must be an integer from 1 to 8') from None
    if not 1<=value<=8:
        raise ValueError('HOLMES_MAX_CONCURRENCY must be an integer from 1 to 8')
    return value


SLOTS = threading.BoundedSemaphore(concurrency_limit())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path != "/health":
            return self.respond(404, {"ready": False})
        self.respond(200, {"service": "isolated-holmes", "ready": bool(TOKEN), "scope": "service_not_provider_acceptance"})

    def do_POST(self):
        if not TOKEN or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + TOKEN):
            return self.respond(401, {"ready": False, "reason": "unauthorized"})
        if self.path != "/investigate":
            return self.respond(404, {"ready": False})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1024 * 1024:
                return self.respond(413, {"ready": False, "reason": "invalid_body_size"})
            raw = self.rfile.read(length)
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError()
        except Exception:
            return self.respond(400, {"ready": False, "reason": "invalid_json"})
        if not SLOTS.acquire(blocking=False):
            return self.respond(429, {"ready": False, "reason": "service_busy"})
        try:
            environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "LITELLM_LOCAL_MODEL_COST_MAP": "true", "OTEL_SDK_DISABLED": "true"}
            process = subprocess.run([sys.executable, str(Path(__file__).with_name("holmes_runner.py"))],
                input=raw, capture_output=True, timeout=72, check=False, env=environment)
            if process.returncode or len(process.stdout) > 128 * 1024:
                raise ValueError()
            result = json.loads(process.stdout)
            if not isinstance(result, dict):
                raise ValueError()
            self.respond(200, result)
        except Exception:
            self.respond(502, {"integration": "holmes", "ready": False, "reason": "isolated_investigation_failed"})
        finally:
            SLOTS.release()


if __name__ == "__main__":
    if len(TOKEN) < 24:
        raise SystemExit("HOLMES_SERVICE_TOKEN must contain at least 24 characters")
    server = ThreadingHTTPServer((os.environ.get("HOLMES_SERVICE_BIND", "0.0.0.0"), 8093), Handler)
    server.daemon_threads = True
    server.serve_forever()
