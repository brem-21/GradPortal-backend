"""Find the person to email about an opportunity.

Confidence encodes provenance, and the UI surfaces it, because a generic
info@ address deserves a different tone than a named admissions officer.
"""

import re

from selectolax.parser import HTMLParser

from app.agent.base import RawContact

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

# Addresses that are never a useful outreach target.
EMAIL_BLOCKLIST = re.compile(
    r"(webmaster|noreply|no-reply|donotreply|postmaster|privacy|abuse|unsubscribe"
    r"|example\.(com|org)|sentry\.io|wixpress|\.png$|\.jpg$|\.svg$)",
    re.IGNORECASE,
)

ROLE_HINTS = [
    (r"admissions?\s+(officer|coordinator|director|manager|team)", "Admissions", 0.9),
    (
        r"graduate\s+(coordinator|advisor|adviser|program director|secretary)",
        "Graduate Coordinator",
        0.9,
    ),
    (r"(principal investigator|PI)\b", "Principal Investigator", 0.9),
    (r"scholarship\s+(officer|coordinator|team|office)", "Scholarship Office", 0.9),
    (r"(programme?|program)\s+(director|lead|manager)", "Programme Director", 0.85),
    (r"(professor|prof\.|dr\.)", "Faculty", 0.8),
    (r"(recruit(ing|er|ment)|talent)", "Recruiter", 0.8),
    (r"enquir(y|ies)|inquir(y|ies)|contact us|get in touch", "General Enquiries", 0.6),
]

# Local-parts that are clearly departmental rather than personal.
GENERIC_LOCALPARTS = {
    "info",
    "contact",
    "enquiries",
    "inquiries",
    "admissions",
    "graduate",
    "gradadmissions",
    "hello",
    "office",
    "support",
    "apply",
    "study",
    "scholarships",
    "hr",
    "careers",
    "jobs",
}

NAME_NEAR_EMAIL = re.compile(
    r"(?:(?:Prof|Professor|Dr|Mr|Ms|Mrs)\.?\s+)?"
    r"([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,2})"
)
PHONE_RE = re.compile(
    r"(?:\+\d{1,3}[\s\-.]?)?(?:\(\d{1,4}\)[\s\-.]?)?\d{3,4}[\s\-.]?\d{3,4}(?:[\s\-.]?\d{2,4})?"
)


def _score_email(email: str, context: str) -> tuple[str | None, float]:
    """Return (role label, confidence) for an address given its surrounding text."""
    local = email.split("@")[0].lower()
    window = context.lower()

    for pattern, label, confidence in ROLE_HINTS:
        if re.search(pattern, window, re.IGNORECASE):
            return label, confidence

    if local in GENERIC_LOCALPARTS or any(local.startswith(g) for g in GENERIC_LOCALPARTS):
        return "General Enquiries", 0.55
    if "." in local or "_" in local:
        # first.last@ is almost always a real person.
        return None, 0.75
    return None, 0.6


def _nearby_name(context: str, email: str) -> str | None:
    before = context.split(email)[0][-160:] if email in context else context[-160:]
    matches = NAME_NEAR_EMAIL.findall(before)
    if matches:
        candidate = matches[-1].strip()
        if 4 <= len(candidate) <= 60 and not re.search(
            r"\b(Apply|Deadline|Program|University|Department|Contact|Email)\b", candidate
        ):
            return candidate
    return None


def extract_contacts_from_html(
    html: str,
    source_url: str | None = None,
    limit: int = 5,
) -> list[RawContact]:
    if not html:
        return []

    tree = HTMLParser(html)
    for tag in tree.css("script, style, noscript"):
        tag.decompose()

    found: dict[str, RawContact] = {}

    # mailto: links are the highest-signal source — they were put there to be used.
    for node in tree.css('a[href^="mailto:"]'):
        href = node.attributes.get("href", "")
        address = href.removeprefix("mailto:").split("?")[0].strip()
        if not EMAIL_RE.fullmatch(address) or EMAIL_BLOCKLIST.search(address):
            continue
        parent_text = node.parent.text(separator=" ", strip=True) if node.parent else node.text()
        role, confidence = _score_email(address, parent_text)
        link_text = node.text(strip=True)
        name = (
            link_text if link_text and "@" not in link_text else _nearby_name(parent_text, address)
        )
        found[address.lower()] = RawContact(
            name=name,
            role=role,
            email=address,
            source_url=source_url,
            confidence=min(1.0, confidence + 0.1),
        )

    # Then plain-text addresses in the body.
    text = (
        tree.body.text(separator=" ", strip=True)
        if tree.body
        else tree.text(separator=" ", strip=True)
    )
    for match in EMAIL_RE.finditer(text):
        address = match.group(0)
        key = address.lower()
        if key in found or EMAIL_BLOCKLIST.search(address):
            continue
        window = text[max(0, match.start() - 200) : match.end() + 120]
        role, confidence = _score_email(address, window)
        found[key] = RawContact(
            name=_nearby_name(window, address),
            role=role,
            email=address,
            source_url=source_url,
            confidence=confidence,
        )

    contacts = sorted(found.values(), key=lambda c: c.confidence, reverse=True)[:limit]
    if contacts:
        phone = PHONE_RE.search(text)
        if phone and len(re.sub(r"\D", "", phone.group(0))) >= 9:
            contacts[0].phone = phone.group(0).strip()
    return contacts


def pick_primary(contacts: list[RawContact]) -> RawContact | None:
    if not contacts:
        return None
    return max(contacts, key=lambda c: (c.confidence, bool(c.name)))
