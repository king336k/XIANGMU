# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

import json
import logging
import logging.handlers as handlers
import os
import re
import time
import traceback
from itertools import islice
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class SizedTimedRotatingFileHandler(handlers.TimedRotatingFileHandler):
    """
    Handler for logging to a set of files, which switches from one file
    to the next when the current file reaches a certain size, or at certain
    timed intervals
    """

    def __init__(
        self,
        filename,
        maxBytes=0,
        backupCount=0,
        encoding=None,
        delay=0,
        when="h",
        interval=1,
        utc=False,
    ):
        handlers.TimedRotatingFileHandler.__init__(self, filename, when, interval, backupCount, encoding, delay, utc)
        self.maxBytes = maxBytes

    def shouldRollover(self, record):
        """
        Determine if rollover should occur.

        Basically, see if the supplied record would cause the file to exceed
        the size limit we have.
        """
        if self.stream is None:  # delay was set...
            self.stream = self._open()
        if self.maxBytes > 0:  # are we rolling over?
            msg = "%s\n" % self.format(record)
            # due to non-posix-compliant Windows feature
            self.stream.seek(0, 2)
            if self.stream.tell() + len(msg) >= self.maxBytes:
                return 1
        t = int(time.time())
        if t >= self.rolloverAt:
            return 1
        return 0

# Request/activity logging is an untrusted-data boundary. Keep bounded context,
# redact secrets before console/file handlers or asynchronous DB logging.

REDACTED = "[REDACTED]"
LOG_LIMIT = 8192
_SECRET_KEY = re.compile(
    r"password|passwd|pwd|secret|token|apikey|bridgekey|servicekey|signingkey|accesskey|authorization|cookie|credential|signature|"
    r"密码|密钥|口令|令牌|凭据", re.I
)
_ASSIGNMENT = re.compile(
    r"(?i)([\"']?(?:password|passwd|pwd|[a-z0-9_-]*(?:secret|token|api[_-]?key|credential|signature)|"
    r"token|secret|api[_-]?key|credential|signature|authorization|proxy-authorization|cookie|set-cookie|密码|密钥|口令|令牌|凭据)[\"']?\s*[:=]\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s&,;\r\n}]+)"
)
_BEARER = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9_+/.=:-]+")
_JSON_ESCAPE = re.compile(r'\\u([0-9a-fA-F]{4})|\\(["\\/])')


def sensitive_log_key(key):
    return bool(_SECRET_KEY.search(re.sub(r"[_\W]", "", str(key))))


def safe_log_text(value, limit=LOG_LIMIT, _depth=0):
    text = str(value)
    # Truncating first destroys closing JSON quotes or URL userinfo boundaries,
    # leaving an apparently harmless prefix that may still contain a secret.
    if len(text) > limit:
        return "[context omitted: budget]"
    if text.lstrip().startswith(("{", "[")):
        if _depth >= 4:
            return "[context omitted: depth]"
        try:
            return json.dumps(safe_log_value(json.loads(text), _depth+1), ensure_ascii=False)
        except (ValueError, TypeError):
            pass
    # Free text can include escaped JSON without itself being a JSON document.
    # Decode only JSON escapes, with a fixed pass budget. If the decoded text
    # contains credentials, omit the opaque context rather than guessing where
    # an escaped value ends and leaking a suffix after an embedded quote.
    decoded = text
    for _ in range(4):
        unescaped = _JSON_ESCAPE.sub(lambda match: chr(int(match[1], 16)) if match[1] else match[2], decoded)
        if unescaped == decoded:
            break
        decoded = unescaped
    if _JSON_ESCAPE.search(decoded):
        return "[context omitted: escape budget]"
    if decoded != text and (_ASSIGNMENT.search(decoded) or _BEARER.search(decoded)):
        return "[context omitted: escaped credential]"
    text = re.sub(r"-----BEGIN [^-\n]*PRIVATE KEY-----.*?(?:-----END [^-\n]*PRIVATE KEY-----|$)", "[PRIVATE KEY REDACTED]", text, flags=re.S)
    text = re.sub(r"(?im)((?:proxy-)?authorization|(?:set-)?cookie)(\s*:\s*)[^\r\n]+", lambda match: match[1] + match[2] + REDACTED, text)
    # Connection URLs in exceptions may contain userinfo, even outside HTTP.
    text = re.sub(r"([A-Za-z][A-Za-z0-9+.-]*://)[^/\s?#]*@", r"\1[REDACTED]@", text)
    def url_query(match):
        try:
            parts = urlsplit(match[0])
            return urlunsplit((parts.scheme, parts.netloc, parts.path, safe_query(parts.query), parts.fragment))
        except ValueError:
            return "[URL omitted]"
    text = re.sub(r"https?://[^\s<>\"']+", url_query, text) if "?" in text else text
    text = _BEARER.sub(lambda match: match[1] + " " + REDACTED, text)
    text = _ASSIGNMENT.sub(lambda match: match[1] + REDACTED, text)
    return text


def safe_query(query):
    # parse_qsl decodes keys before matching and preserves repeated filters.
    if len(query) > LOG_LIMIT:
        return "[query omitted: budget]"
    try:
        pairs = parse_qsl(query, keep_blank_values=True, max_num_fields=100)
    except ValueError:
        return "[query omitted: budget]"
    return urlencode([(key, REDACTED if sensitive_log_key(key) else safe_log_text(value, 512)) for key, value in pairs])


def safe_log_value(value, depth=0, _budget=None):
    budget = _budget if _budget is not None else [200, LOG_LIMIT]
    budget[0] -= 1
    if depth > 8 or budget[0] < 0 or budget[1] <= 0:
        return "[omitted: budget]"
    if isinstance(value, dict):
        return {safe_log_text(key, 100): REDACTED if sensitive_log_key(key) else safe_log_value(item, depth+1, budget)
                for key, item in islice(value.items(), 100)}
    if isinstance(value, (list, tuple)):
        return [safe_log_value(item, depth+1, budget) for item in value[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = safe_log_text(value, min(LOG_LIMIT, budget[1]), depth)
    budget[1] -= len(text)
    return text


class SafeLogFilter(logging.Filter):
    """Bound per-record work; retain traceback frame locations while hiding secret values."""
    def filter(self, record):
        record.msg = safe_log_text(record.getMessage())
        record.args = ()
        if record.exc_info:
            formatted = logging.Formatter().formatException(record.exc_info)
            if len(formatted) > 16384:
                # Retain trusted traceback locations/type while omitting the
                # oversized exception value and source lines, which are data.
                frames = [
                    f'  File "{safe_log_text(frame.f_code.co_filename, 256)}", line {line}, in {safe_log_text(frame.f_code.co_name, 128)}'
                    for frame, line in islice(traceback.walk_tb(record.exc_info[2]), 20)
                ]
                exception_type = safe_log_text(record.exc_info[0].__name__, 128)
                record.exc_text = "Traceback (bounded):\n" + "\n".join(frames) + f"\n{exception_type}: [context omitted: budget]"
            else:
                record.exc_text = safe_log_text(formatted, 16384)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = safe_log_text(record.exc_text, 16384)
        standard = {"msg", "args", "exc_info", "exc_text"}
        for index, (key, value) in enumerate(list(record.__dict__.items())):
            # Formatters serialize arbitrary extras. Never leave later values
            # untouched merely because the sanitization budget was reached.
            if index >= 64 and key not in standard:
                del record.__dict__[key]
                continue
            if key not in standard:
                if sensitive_log_key(key):
                    record.__dict__[key] = REDACTED
                else:
                    record.__dict__[key] = safe_log_value(value)
        return True


class ProcessRotatingFileHandler(handlers.RotatingFileHandler):
    """Size-bounded per-process files, including prefork children, with numbered backups."""
    def __init__(self, filename, **kwargs):
        self.process_filename = filename
        self.process_id = os.getpid()
        super().__init__(self._filename(), **kwargs)

    def _filename(self):
        stem, extension = os.path.splitext(self.process_filename)
        return f"{stem}.{os.getpid()}{extension}"

    def shouldRollover(self, record):
        if self.stream is None:
            self.stream = self._open()
        self.stream.seek(0, 2)
        text = self.format(record) + "\n"
        encoding = "utf-8" if self.encoding in {None, "locale"} else self.encoding
        return bool(self.maxBytes > 0 and self.stream.tell() + len(text.encode(encoding, errors="replace")) >= self.maxBytes)

    def emit(self, record):
        if self.process_id != os.getpid():
            self.acquire()
            try:
                if self.stream:
                    self.stream.close()
                self.process_id = os.getpid()
                self.baseFilename = os.path.abspath(self._filename())
                self.stream = None
            finally:
                self.release()
        super().emit(record)
