"""Inject a local unresponsive provider without changing active model settings."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import sys
import threading
import time

import django
sys.path.insert(0, "/code")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "plane.settings.production")
django.setup()
from plane.quality.diagnostic_model import analyze_diagnostic

calls = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        calls.append(time.monotonic())
        time.sleep(130)

    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
start = time.monotonic()
try:
    analyze_diagnostic({"model": "local-timeout-fixture", "api_key": "synthetic-not-a-credential",
                        "base_url": f"http://127.0.0.1:{server.server_port}/v1"}, "ERROR connection refused", [], [])
    result = {"unexpected_success": True}
except Exception as error:
    result = {"error_class": type(error).__name__, "safe_error": str(error)}
finally:
    server.shutdown()
    server.server_close()
print(json.dumps({**result, "elapsed_s": round(time.monotonic() - start, 3), "provider_requests": len(calls),
                  "external_model_called": False, "active_model_configuration_changed": False}))
