"""Named exit codes for the orchestrator CLI.

Every code has a clear, predictable meaning.  Use these instead of bare
integers so that call sites are self-documenting and greppable.
"""

# ── Success ──────────────────────────────────────────────────────────────
OK = 0  # everything worked as expected

# ── Failure ──────────────────────────────────────────────────────────────
ERROR = 1  # general / unexpected error

# ── Blocked ──────────────────────────────────────────────────────────────
BLOCKED = 2  # a safety gate or policy prevented the operation

# ── Invalid ──────────────────────────────────────────────────────────────
INVALID = 3  # bad arguments, missing config, malformed input
