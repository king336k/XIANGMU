"""Fixed failure observations only; never provider messages, bodies or request data."""

import json

SOURCES = {"agent_transport", "agent_deadline", "subprocess_deadline", "pre_model_materials", "direct_sdk", "unknown"}
PHASES = {"connect", "read", "write", "pool", "unknown"}
DEADLINES = {
    "request_timeout",
    "first_event_timeout",
    "agent_run",
    "subprocess_deadline",
    "pre_model_materials",
    "unknown",
}
CODES = {
    "MODEL_TIMEOUT",
    "MODEL_FAILED",
    "AGENT_FAILED",
    "AGENT_USAGE_LIMIT",
    "AGENT_PROVIDER_AUTH",
    "AGENT_PROVIDER_UNAVAILABLE",
    "AGENT_INVALID_OUTPUT",
    "INVALID_DIAGNOSTIC_OUTPUT",
    "INVALID_DIAGNOSTIC_CITATION",
    "SENSITIVE_DIAGNOSTIC_OUTPUT",
}


def safe_model_failure(value):
    value = value if isinstance(value, dict) else {}
    result = {}
    for key, allowed in [("source", SOURCES), ("transport_phase", PHASES), ("deadline_kind", DEADLINES)]:
        item = value.get(key)
        result[key] = item if type(item) is str and item in allowed else "unknown"
    if type(value.get("provider_called")) is bool:
        result["provider_called"] = value["provider_called"]
    return result


class DiagnosticTimeoutFailure(TimeoutError):
    def __init__(self, code, failure=None):
        super().__init__(code)
        self.model_failure = safe_model_failure(failure)


class DiagnosticProviderFailure(ValueError):
    def __init__(self, code, failure=None):
        super().__init__(code)
        self.model_failure = safe_model_failure(failure)


def agent_failure_metadata(stderr, fallback=None):
    if isinstance(stderr, str):
        for line in reversed(stderr.splitlines()[-8:]):
            if len(line) > 16384:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and isinstance(data.get("model_failure"), dict):
                return safe_model_failure(data["model_failure"])
    return safe_model_failure(fallback)


def failure_from_exception(error):
    if isinstance(getattr(error, "model_failure", None), dict):
        return safe_model_failure(error.model_failure)
    source = (
        "direct_sdk" if any(cls.__module__.partition(".")[0] == "openai" for cls in type(error).__mro__) else "unknown"
    )
    phase = "unknown"
    names = {"ConnectTimeout": "connect", "ReadTimeout": "read", "WriteTimeout": "write", "PoolTimeout": "pool"}
    cause, seen = error, set()
    while cause is not None and id(cause) not in seen and len(seen) < 8:
        seen.add(id(cause))
        for cls in type(cause).__mro__:
            if (
                cls.__module__.partition(".")[0] in {"httpx", "httpx2", "httpcore", "httpcore2"}
                and cls.__name__ in names
            ):
                phase = names[cls.__name__]
                break
        if phase != "unknown":
            break
        cause = cause.__cause__ or cause.__context__
    return safe_model_failure({"source": source, "transport_phase": phase})


def safe_attempt_failures(value):
    rows = {}
    for row in value[:4] if isinstance(value, list) else []:
        if not isinstance(row, dict) or type(row.get("attempt")) is not int or not 1 <= row["attempt"] <= 4:
            continue
        code, duration = row.get("code"), row.get("duration_ms")
        if type(code) is not str or code not in CODES or type(duration) is not int or not 0 <= duration <= 86400000:
            continue
        rows[row["attempt"]] = {
            "attempt": row["attempt"],
            "code": code,
            "duration_ms": duration,
            **safe_model_failure(row),
        }
    return [rows[key] for key in sorted(rows)]


def append_attempt_failure(result):
    code = result.get("model_error_code")
    if type(code) is not str or code not in CODES:
        return
    retry = result.get("retry")
    count = retry.get("count", 0) if isinstance(retry, dict) else 0
    count = min(3, max(0, count)) if type(count) is int else 0
    duration = result.get("duration_ms", 0)
    duration = min(86400000, max(0, duration)) if type(duration) is int else 0
    history = safe_attempt_failures(result.get("attempt_failures"))
    history = [row for row in history if row["attempt"] != count + 1]
    history.append(
        {"attempt": count + 1, "code": code, "duration_ms": duration, **safe_model_failure(result.get("model_failure"))}
    )
    result["attempt_failures"] = sorted(history, key=lambda row: row["attempt"])[-4:]
