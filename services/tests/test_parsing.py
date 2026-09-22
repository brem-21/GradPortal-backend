import pytest

from doc_service.parsing import parse
from shared.errors import ValidationError


def test_parses_plain_text(sample_cv_text: str):
    parsed = parse(sample_cv_text.encode(), "text/plain", "cv.txt")
    assert "JANE OKONKWO" in parsed.text
    assert "0.91 mIoU" in parsed.text


def test_parses_docx_including_tables(sample_docx_bytes: bytes):
    parsed = parse(
        sample_docx_bytes,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "cv.docx",
    )
    assert "Data Engineering Intern" in parsed.text
    assert "ICLR 2026" in parsed.text


def test_falls_back_to_extension_when_content_type_is_generic(sample_cv_text: str):
    parsed = parse(sample_cv_text.encode(), "application/octet-stream", "cv.txt")
    assert "EDUCATION" in parsed.text


def test_rejects_legacy_doc_with_actionable_message():
    with pytest.raises(ValidationError, match="Save it as .docx"):
        parse(b"\xd0\xcf\x11\xe0" + b"x" * 200, "application/msword", "cv.doc")


def test_rejects_unsupported_type():
    with pytest.raises(ValidationError, match="Unsupported file type"):
        parse(b"fake image bytes here padded out", "image/png", "scan.png")


def test_rejects_empty_document():
    with pytest.raises(ValidationError, match="empty"):
        parse(b"hi", "text/plain", "tiny.txt")


def test_normalises_whitespace_and_nbsp():
    raw = "Title\r\n\r\n\r\n\r\nBody\xa0text   with    gaps"
    parsed = parse(
        raw.encode() + b" padding to clear the length floor here ok", "text/plain", "a.txt"
    )
    assert "\r" not in parsed.text
    assert "\xa0" not in parsed.text
    assert "\n\n\n" not in parsed.text
