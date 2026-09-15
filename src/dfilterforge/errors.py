"""Shared error base for every dfilterforge boundary.

Each boundary module keeps its own subclass so callers can still catch
``RunnerError`` or ``CompileError`` specifically, but the code/message
contract lives in one place.
"""

from __future__ import annotations


class DFilterForgeError(Exception):
    """An error with a stable machine-readable code and a safe message.

    ``code`` is meant for JSON output and tests; ``message`` must not contain
    packet payloads, secrets, or untrusted model text.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
