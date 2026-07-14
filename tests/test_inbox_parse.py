from email.message import EmailMessage

import pytest

from japp.inbox.parse import is_approved_sender, parse_command, sender_address


@pytest.mark.parametrize("subject,expected", [
    ("TAILOR 42", ("tailor", 42)),
    ("tailor 7", ("tailor", 7)),
    ("Re: TAILOR 42", ("tailor", 42)),
    ("RE: re: tailor 7", ("tailor", 7)),
    ("Fwd: TAILOR 3", ("tailor", 3)),
    ("Fw: TAILOR 3", ("tailor", 3)),
    ("  TAILOR 12  ", ("tailor", 12)),
    ("TAILOR 12 please", ("tailor", 12)),
])
def test_parse_command_accepts(subject, expected):
    assert parse_command(subject) == expected


@pytest.mark.parametrize("subject", [
    "TAILORX 1",
    "TAILOR",
    "TAILOR abc",
    "[japp] Tailored resume: Acme - PM",     # our own reply must never match
    "Tailored resume attached",
    "please TAILOR 12",                      # command must lead the subject
    "",
])
def test_parse_command_rejects(subject):
    assert parse_command(subject) is None


def test_parse_command_handles_none():
    assert parse_command(None) is None


def test_sender_address_lowercases_and_strips_display_name():
    msg = EmailMessage()
    msg["From"] = "Bro Name <Bro@Gmail.com>"
    assert sender_address(msg) == "bro@gmail.com"


def test_sender_address_missing_header():
    assert sender_address(EmailMessage()) == ""


def test_is_approved_sender_case_insensitive():
    assert is_approved_sender("bro@gmail.com", "Bro@Gmail.com")
    assert not is_approved_sender("evil@gmail.com", "bro@gmail.com")
    assert not is_approved_sender("", "bro@gmail.com")
