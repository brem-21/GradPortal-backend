from app.agent.contacts import extract_contacts_from_html, pick_primary

PAGE = """
<html><body>
  <div class="contact">
    <p>For enquiries contact the Admissions Officer, Dr. Aoife Brennan,
       at <a href="mailto:a.brennan@inf.ed.ac.uk">a.brennan@inf.ed.ac.uk</a>.</p>
    <p>General questions: info@ed.ac.uk</p>
    <p>Tel: +44 131 650 1000</p>
  </div>
  <img src="logo.png"> <a href="mailto:webmaster@ed.ac.uk">webmaster</a>
  <script>var t = "tracking@sentry.io";</script>
</body></html>
"""


def test_finds_mailto_and_plaintext():
    contacts = extract_contacts_from_html(PAGE, "https://ed.ac.uk/phd")
    emails = {c.email for c in contacts}
    assert "a.brennan@inf.ed.ac.uk" in emails
    assert "info@ed.ac.uk" in emails


def test_blocklist_excludes_noise():
    emails = {c.email for c in extract_contacts_from_html(PAGE)}
    assert "webmaster@ed.ac.uk" not in emails
    assert "tracking@sentry.io" not in emails


def test_named_role_outranks_generic():
    primary = pick_primary(extract_contacts_from_html(PAGE, "https://ed.ac.uk/phd"))
    assert primary is not None
    assert primary.email == "a.brennan@inf.ed.ac.uk"
    assert primary.confidence > 0.7


def test_generic_mailbox_is_lower_confidence():
    contacts = {c.email: c for c in extract_contacts_from_html(PAGE)}
    assert contacts["info@ed.ac.uk"].confidence < contacts["a.brennan@inf.ed.ac.uk"].confidence


def test_empty_html_is_safe():
    assert extract_contacts_from_html("") == []
    assert pick_primary([]) is None
