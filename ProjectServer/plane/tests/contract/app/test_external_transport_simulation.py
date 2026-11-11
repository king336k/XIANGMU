"""Real localhost HTTP response framing must fail closed before accepting Feishu text.

Only the test Session transport maps the fixed official URL to localhost; product
allowlists and endpoint selection are unchanged. No database, source export,
credentials, remote network, model, or message delivery is used.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
import requests

from plane.quality.document_imports import feishu_get
from plane.quality.platform import PlatformUnavailable


@pytest.mark.contract
@pytest.mark.parametrize("mode", ["truncated", "disconnect", "invalid", "wrong_shape"])
def test_feishu_raw_real_http_transport_rejects_incomplete_response(monkeypatch, mode):
    requests_seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests_seen.append(self.path)
            if mode == "disconnect":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            body = (
                b"invalid-json"
                if mode == "invalid"
                else json.dumps(
                    [] if mode == "wrong_shape" else {"code": 0, "data": {"content": "fixture text"}}
                ).encode()
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(body) + (10 if mode == "truncated" else 0)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original_send = requests.sessions.Session.send

    def local_transport(session, request, **kwargs):
        parsed = urlsplit(request.url)
        assert parsed.scheme == "https" and parsed.hostname == "open.feishu.cn"
        assert parsed.path == "/open-apis/docx/v1/documents/Fixture152/raw_content"
        request.url = f"http://127.0.0.1:{server.server_port}" + parsed.path
        return original_send(session, request, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "send", local_transport)
    try:
        with pytest.raises(PlatformUnavailable):
            feishu_get({"service_token": "fixture-not-a-secret"}, "/open-apis/docx/v1/documents/Fixture152/raw_content")
        assert requests_seen == ["/open-apis/docx/v1/documents/Fixture152/raw_content"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
