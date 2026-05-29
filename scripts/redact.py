#!/usr/bin/env python3
"""Secret-safe text redaction for operator diagnostics."""

from __future__ import annotations

import re
import sys


SECRET_KEY_RE = re.compile(
    r"""(?ix)
    \b(
        [A-Z0-9_]*(?:API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSPHRASE|PRIVATE[_-]?KEY|ACCESS[_-]?TOKEN)[A-Z0-9_]*
    )
    (\s*[:=]\s*)
    (?:
        "([^"\n]*)" |
        '([^'\n]*)' |
        ([^\s,;]+)
    )
    """
)

AUTH_HEADER_RE = re.compile(
    r"(?i)\b(Authorization\s*:\s*)(?:Bearer\s+)?[A-Za-z0-9._~+/=-]{8,}"
)

BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}")

ACCOUNT_RE = re.compile(r"(?i)\b(Account\s*:\s*)([^|\s,;]+)")

NAMED_ID_RE = re.compile(
    r"""(?ix)
    \b(
        account[_-]?id |
        account[_-]?number |
        account[_-]?uuid |
        account[_-]?identifier |
        key[_-]?id |
        api[_-]?key[_-]?id |
        id
    )
    (\s*[:=]\s*)
    ([^\s,;|]+)
    """
)

UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

API_KEY_LIKE_RE = re.compile(r"\b(?:PK|AK|SK|APCA|CB)[A-Z0-9_=-]{12,}\b")


def _redact_secret_assignment(match: re.Match[str]) -> str:
    key = match.group(1)
    sep = match.group(2)
    return f"{key}{sep}[REDACTED_SECRET]"


def _redact_named_id(match: re.Match[str]) -> str:
    key = match.group(1)
    sep = match.group(2)
    return f"{key}{sep}[REDACTED_ID]"


def redact_text(text: str) -> str:
    """Return text with obvious account identifiers and secrets redacted."""
    redacted = SECRET_KEY_RE.sub(_redact_secret_assignment, text)
    redacted = AUTH_HEADER_RE.sub(r"\1[REDACTED_SECRET]", redacted)
    redacted = BEARER_RE.sub("Bearer [REDACTED_SECRET]", redacted)
    redacted = ACCOUNT_RE.sub(r"\1[REDACTED_ACCOUNT]", redacted)
    redacted = NAMED_ID_RE.sub(_redact_named_id, redacted)
    redacted = UUID_RE.sub("[REDACTED_ID]", redacted)
    redacted = API_KEY_LIKE_RE.sub("[REDACTED_SECRET]", redacted)
    return redacted


def main() -> int:
    sys.stdout.write(redact_text(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
