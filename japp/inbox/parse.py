"""Command parsing for the reply-by-email approval loop (pure logic, no I/O).

The digest's mailto button pre-fills a reply whose subject is "TAILOR <id>".
Only the subject is trusted: bodies arrive with quoted text, signatures, and
client-specific wrapping.
"""

from __future__ import annotations

import email.utils
import re
from email.message import Message

# One or more stacked reply/forward prefixes: "Re:", "RE: Fwd:", "fw:" ...
_PREFIXES = re.compile(r"^\s*(?:(?:re|fwd?|fw)\s*:\s*)+", re.IGNORECASE)
# Anchored at the start so "[japp] Tailored resume: ..." replies never match.
_COMMAND = re.compile(r"^TAILOR\s+(\d+)\b", re.IGNORECASE)


def parse_command(subject: str) -> tuple[str, int] | None:
    """-> ("tailor", job_id) or None if the subject is not a command."""
    stripped = _PREFIXES.sub("", subject or "").strip()
    m = _COMMAND.match(stripped)
    if m is None:
        return None
    return ("tailor", int(m.group(1)))


def sender_address(msg: Message) -> str:
    """Bare lowercased address from the From header ('Bo <Bo@X.com>' -> 'bo@x.com')."""
    _, addr = email.utils.parseaddr(str(msg.get("From", "")))
    return addr.lower()


def is_approved_sender(addr: str, approved: str) -> bool:
    return bool(addr) and addr.lower() == approved.lower()
