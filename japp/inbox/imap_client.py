"""IMAP access behind a small interface so the pipeline is testable offline.

Deliberately read-only: the mailbox is selected readonly and messages are
fetched with BODY.PEEK[], so no flags are ever set. Idempotency comes from
the email_requests table keyed by (UIDVALIDITY, UID), not from \\Seen.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
from email.message import EmailMessage


class ImapMailbox:
    """The INBOX of one IMAP account. Satisfies the Mailbox shape run_inbox needs:
    uidvalidity(), search_command_uids(), fetch(uid), close()."""

    def __init__(self, host: str, port: int, user: str, password: str):
        self._conn = imaplib.IMAP4_SSL(host, port)
        self._conn.login(user, password)
        self._conn.select("INBOX", readonly=True)

    def uidvalidity(self) -> int:
        value = self._conn.response("UIDVALIDITY")[1][0]
        return int(value)

    def search_command_uids(self) -> list[int]:
        """UIDs of messages whose subject contains TAILOR (server-side substring
        search; the strict command grammar is applied later in parse.py)."""
        _, data = self._conn.uid("SEARCH", None, 'SUBJECT "TAILOR"')
        return [int(u) for u in (data[0] or b"").split()]

    def fetch(self, uid: int) -> EmailMessage:
        _, data = self._conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
        raw = data[0][1]
        return email.message_from_bytes(raw, policy=email.policy.default)

    def close(self) -> None:
        try:
            self._conn.logout()
        except Exception:
            pass


def open_mailbox(host: str, port: int, user: str, password: str) -> ImapMailbox:
    return ImapMailbox(host, port, user, password)
