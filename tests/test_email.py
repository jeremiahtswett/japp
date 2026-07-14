from japp.digest.email import build_message

ENV = {"SMTP_USER": "japp@test.com", "DIGEST_TO_EMAIL": "bro@test.com"}


def test_build_message_defaults_to_digest_recipient():
    msg = build_message(ENV, "subj", "body text", "<p>body html</p>")
    assert msg["From"] == "japp@test.com"
    assert msg["To"] == "bro@test.com"
    assert msg["Subject"] == "subj"
    assert msg.get_body(("plain",)).get_content().strip() == "body text"
    assert "<p>body html</p>" in msg.get_body(("html",)).get_content()
    assert list(msg.iter_attachments()) == []


def test_build_message_to_override():
    msg = build_message(ENV, "s", "t", to="other@test.com")
    assert msg["To"] == "other@test.com"


def test_build_message_docx_attachment(tmp_path):
    docx = tmp_path / "tailored_resume.docx"
    docx.write_bytes(b"PK\x03\x04 fake docx")
    msg = build_message(ENV, "s", "t", attachments=[docx])
    (att,) = msg.iter_attachments()
    assert att.get_filename() == "tailored_resume.docx"
    assert att.get_content_type() == \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert att.get_content() == b"PK\x03\x04 fake docx"


def test_build_message_unknown_extension_falls_back():
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "notes.unknownext"
        p.write_bytes(b"hello")
        msg = build_message(ENV, "s", "t", attachments=[p])
        (att,) = msg.iter_attachments()
        assert att.get_content_type() == "application/octet-stream"
