"""Local candidate OCR HTTP boundary. No remote OCR, model calls, or payload logging."""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

MAX_BODY = 20 * 1024 * 1024
MAX_RESPONSE = 2 * 1024 * 1024
LIMITS = {'body_bytes': MAX_BODY, 'metadata_bytes': MAX_RESPONSE, 'concurrency': 1,
          'job_seconds': 120, 'page_seconds': 15, 'pages_or_images': 20,
          'page_pixels': 9_000_000, 'total_pixels': 60_000_000, 'text_characters': 100000,
          'languages': ['chi_sim', 'eng'], 'types': ['pdf', 'docx', 'png']}


def extract(raw, kind, digest):
    parent = Path(os.environ.get('DOCUMENT_OCR_WORK_DIR', '/work'))
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='ocr-', dir=parent) as directory:
        path = Path(directory) / ('source.' + kind)
        path.write_bytes(raw)
        path.chmod(0o600)
        env = {**os.environ, 'TMPDIR': directory, 'OMP_THREAD_LIMIT': '2', 'OPENBLAS_NUM_THREADS': '1'}
        process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('extractor.py')), str(path)],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=env, start_new_session=True)
        try:
            output, _ = process.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            return failure(digest, 'document_timeout')
        if len(output) > MAX_RESPONSE:
            return failure(digest, 'metadata_budget')
        try:
            result = json.loads(output)
        except (ValueError, UnicodeDecodeError):
            return failure(digest, 'extraction_failed')
        segments = []
        for index, item in enumerate(result.get('segments', []), 1):
            segment = {'key': f'ocr-{index}', 'text': item['text'], 'method': 'ocr',
                       'width': item['width'], 'height': item['height']}
            for source, target in [('page', 'page'), ('part', 'part'), ('paragraph', 'paragraph'), ('image', 'source_image')]:
                if item.get(source) is not None:
                    segment[target] = item[source]
            if kind == 'png':segment['source_image'] = '原始PNG'
            segments.append(segment)
        failures = []
        for item in result.get('failures', []):
            allowed = {key: item[key] for key in ['page', 'part', 'paragraph', 'error'] if item.get(key) is not None}
            failures.append(allowed or {'error': 'extraction_failed'})
        if not segments and not failures:
            failures.append({'error': 'no_recognized_text'})
        return {'status': 'completed', 'source_sha256': digest, 'engine': 'tesseract',
                'segments': segments, 'failures': failures, 'requires_review': True}


def failure(digest, error):
    return {'status': 'completed', 'source_sha256': digest, 'engine': 'tesseract',
            'segments': [], 'failures': [{'error': error}], 'requires_review': True}


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def handle_error(self, request, client_address):
        print(json.dumps({'component':'document-ocr','event':'request_failed'}),flush=True)


def create_server(address, key, extractor=extract):
    if not isinstance(key, str) or len(key) < 16:
        raise ValueError('DOCUMENT_OCR_API_KEY must have at least 16 characters')
    gate = threading.BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.0'

        def log_message(self, *args):
            pass

        def setup(self):
            super().setup()
            self.connection.settimeout(15)
            self.started=time.monotonic()

        def reply(self, status, value):
            body = json.dumps(value, ensure_ascii=False).encode()
            if len(body) > MAX_RESPONSE:
                status, body = 500, b'{"error":"metadata_budget"}'
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if self.path!='/health':
                print(json.dumps({'component':'document-ocr','event':'request','method':self.command,
                    'path':self.path if self.path=='/v1/extract' else '[unmatched]','status':status,
                    'duration_ms':round((time.monotonic()-self.started)*1000)}),flush=True)
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path != '/health':
                return self.reply(404, {'error': 'not_found'})
            return self.reply(200, {'status': 'ready', 'limits': LIMITS})

        def do_POST(self):
            if self.path != '/v1/extract':
                return self.reply(404, {'error': 'not_found'})
            expected = ('Bearer ' + key).encode()
            if not hmac.compare_digest(self.headers.get('Authorization', '').encode('utf-8'), expected):
                return self.reply(401, {'error': 'authentication_required'})
            if self.headers.get('Transfer-Encoding'):
                return self.reply(400, {'error': 'content_length_required'})
            length = self.headers.get('Content-Length', '')
            if not re.fullmatch(r'[0-9]{1,10}', length):
                return self.reply(400, {'error': 'content_length_required'})
            length = int(length)
            if length > MAX_BODY:
                return self.reply(413, {'error': 'body_budget'})
            kind = self.headers.get('X-Document-Type', '')
            digest = self.headers.get('X-Content-SHA256', '')
            if kind not in LIMITS['types'] or not re.fullmatch(r'[a-fA-F0-9]{64}', digest) or length == 0:
                return self.reply(400, {'error': 'invalid_metadata'})
            if self.headers.get('Content-Type') != 'application/octet-stream':
                return self.reply(400, {'error': 'content_type_required'})
            if not gate.acquire(blocking=False):
                return self.reply(429, {'error': 'busy'})
            try:
                raw = self.rfile.read(length)
                if len(raw) != length or hashlib.sha256(raw).hexdigest() != digest.lower():
                    return self.reply(400, {'error': 'content_sha256_mismatch'})
                result = extractor(raw, kind, digest.lower())
                result['requires_review'] = True
                return self.reply(200, result)
            except (TimeoutError, OSError):
                return self.reply(408, {'error': 'request_timeout'})
            except Exception:
                return self.reply(500, {'error': 'extraction_failed'})
            finally:
                gate.release()

    return Server(address, Handler)


if __name__ == '__main__':
    create_server(('0.0.0.0', 18886), os.environ.get('DOCUMENT_OCR_API_KEY', '')).serve_forever()
