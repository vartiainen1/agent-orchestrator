"""Minimal structured logging — stdlib only.

Provides timestamped, level-tagged output to stdout.  Nothing fancy;
the point is that every orchestration action is visible and greppable.

Secrets, API keys, tokens and passwords are never logged.
"""

import sys
from datetime import datetime, timezone

# ── Levels ───────────────────────────────────────────────────────────────
DEBUG = "DEBUG"
INFO = "INFO"
WARN = "WARN"
ERROR = "ERROR"

_LEVEL_ORDER = {DEBUG: 0, INFO: 1, WARN: 2, ERROR: 3}

_current_level = INFO


def set_level(level: str) -> None:
    """Set the minimum logging level (DEBUG / INFO / WARN / ERROR)."""
    level = level.upper()
    if level not in _LEVEL_ORDER:
        raise ValueError(f"unknown level: {level!r} (choose from {list(_LEVEL_ORDER)})")
    global _current_level
    _current_level = level


def get_level() -> str:
    """Return the current minimum logging level."""
    return _current_level


# ── Formatting ───────────────────────────────────────────────────────────

def _ts() -> str:
    """ISO-8601 UTC timestamp, short form."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format(level: str, component: str, message: str) -> str:
    ts = _ts()
    comp = f"[{component}]" if component else ""
    return f"{ts} {level:5s} {comp} {message}"


# ── Public API ───────────────────────────────────────────────────────────

def log(level: str, message: str, *, component: str = "") -> None:
    """Emit a log line if *level* >= the current minimum."""
    if _LEVEL_ORDER.get(level, 0) < _LEVEL_ORDER.get(_current_level, 0):
        return
    line = _format(level, component, message)
    print(line, file=sys.stdout, flush=True)


def debug(message: str, *, component: str = "") -> None:
    log(DEBUG, message, component=component)


def info(message: str, *, component: str = "") -> None:
    log(INFO, message, component=component)


def warn(message: str, *, component: str = "") -> None:
    log(WARN, message, component=component)


def error(message: str, *, component: str = "") -> None:
    log(ERROR, message, component=component)
