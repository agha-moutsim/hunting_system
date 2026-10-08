"""Credentials must never reach a log file.

Exceptions raised by `requests` carry the URL they were raised for, query
string included. SerpApi and every shopping source authenticate by putting
`api_key=...` in that query string, so a single `print(f"... {e}")` writes the
live credential into `be.log` in clear text — which is how this repo's key
ended up on disk (A4).

`scrub()` runs on the failure path only and must itself never raise: it
stringifies, redacts, and returns. The worst case of a missed pattern is a
partial redaction, never an exception inside an error handler.
"""

import re

# `api_key=abc`, `key=abc`, `token=abc`, `Authorization: Bearer abc`, ...
_PARAM = re.compile(
    r"(?i)\b(api[_-]?key|apikey|key|token|access[_-]?token|secret)\s*=\s*"
    r"[^&\s\"'<>]+"
)
_BEARER = re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}")


def scrub(value) -> str:
    """`value` as a string with credential-looking material replaced."""
    text = str(value)
    text = _PARAM.sub(r"\1=[REDACTED]", text)
    return _BEARER.sub(r"\1 [REDACTED]", text)
