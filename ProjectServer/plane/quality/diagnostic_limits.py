"""One deployment budget shared by the provider, agent and task lifecycle."""

import os


def timeout_seconds():
    try:
        value = int(os.environ.get("DIAGNOSTIC_TIMEOUT_SECONDS", "300"))
    except (TypeError, ValueError):
        return 300
    return min(600, max(60, value))


def task_limits():
    soft = timeout_seconds() + 60
    return soft, soft + 20


def queue_wait_seconds():
    try:
        value = int(os.environ.get("DIAGNOSTIC_QUEUE_WAIT_SECONDS", "21600"))
    except (TypeError, ValueError):
        return 21600
    return min(86400, max(900, value))
