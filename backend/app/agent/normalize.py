"""Turn messy scraped text into the enum values and dates the portal indexes on.

Deliberately rule-based rather than model-based: the classification set is small
and closed, and rules are debuggable when a university rewrites its page.
"""

import hashlib
import html
import re
from datetime import date, datetime

from app.core.enums import DegreeLevel, FieldOfStudy, FundingType, OpportunityType

FIELD_PATTERNS: dict[str, list[str]] = {
    FieldOfStudy.ARTIFICIAL_INTELLIGENCE: [
        r"\bartificial intelligence\b",
        r"\bA\.?I\.?\b",
        r"\bmachine learning\b",
        r"\bdeep learning\b",
        r"\bneural network",
        r"\bNLP\b",
        r"\bnatural language processing\b",
        r"\bcomputer vision\b",
        r"\breinforcement learning\b",
        r"\bgenerative ai\b",
        r"\blarge language model",
        r"\brobotics\b",
    ],
    FieldOfStudy.DATA_SCIENCE: [
        r"\bdata science\b",
        r"\bdata scientist\b",
        r"\bstatistical learning\b",
        r"\bcomputational statistics\b",
        r"\bpredictive model",
        r"\bbiostatistics\b",
    ],
    FieldOfStudy.DATA_ENGINEERING: [
        r"\bdata engineer",
        r"\bdata pipeline",
        r"\bETL\b",
        r"\bbig data\b",
        r"\bdata infrastructure\b",
        r"\bdata platform\b",
        r"\bdistributed systems\b",
        r"\bapache spark\b",
        r"\bdata warehous",
    ],
    FieldOfStudy.DATA_ANALYTICS: [
        r"\bdata analytics\b",
        r"\bdata analyst\b",
        r"\bbusiness intelligence\b",
        r"\bbusiness analytics\b",
        r"\bvisual analytics\b",
        r"\bpredictive analytics\b",
        r"\bstatistical analytics\b",
        # Bare "analytics" is deliberately absent: it tagged finance and
        # marketing degrees ("Banking Innovation and Risk Analytics") as data
        # analytics. The qualified forms above carry the actual signal.
    ],
    FieldOfStudy.COMPUTER_SCIENCE: [
        # Spellings taken from real university course catalogues rather than
        # invented: "Cyber Security" is two words about as often as one, and
        # programmes are titled "Computing Science" or "Advanced Computing"
        # at least as often as "Computer Science".
        r"\bcomputer scien\w*\b",
        r"\bcomputing scien\w*\b",
        r"\bcomputing\b",
        r"\bsoftware (engineering|systems|development)\b",
        r"\binformatics\b",
        r"\bcomputer engineering\b",
        r"\bcyber[\s-]?security\b",
        r"\binformation security\b",
        r"\bhuman[\s-]?computer interaction\b",
        r"\btheoretical computer science\b",
        r"\balgorithms\b",
        r"\bdistributed (computing|systems)\b",
        r"\bcomputational (science|engineering)\b",
    ],
}

TYPE_PATTERNS: dict[str, list[str]] = {
    OpportunityType.SCHOLARSHIP: [
        r"\bscholarship\b",
        r"\bbursary\b",
        r"\bgrant\b",
        r"\bfunding award\b",
        r"\bstipend award\b",
    ],
    OpportunityType.FELLOWSHIP: [r"\bfellowship\b", r"\bfellow\b"],
    OpportunityType.ASSISTANTSHIP: [
        r"\bassistantship\b",
        r"\b(graduate|teaching|research) assistant\b",
        r"\bGTA\b",
        r"\bGRA\b",
    ],
    OpportunityType.RESEARCH_POSITION: [
        r"\bresearch position\b",
        r"\bpostdoc",
        r"\bresearch associate\b",
        r"\bPhD position\b",
        r"\bdoctoral position\b",
    ],
    OpportunityType.INTERNSHIP: [
        r"\binternship\b",
        r"\bintern\b",
        r"\bco-?op\b",
        r"\bsummer programme?\b",
    ],
    OpportunityType.GRADUATE_PROGRAM: [
        r"\b(MSc|M\.Sc|MS|MEng|M\.Eng|MA|PhD|Ph\.D|doctoral|master'?s?)\b",
        r"\bgraduate program",
        r"\badmissions?\b",
        r"\bdegree programme?\b",
    ],
    OpportunityType.JOB: [
        r"\bfull.time\b",
        r"\bvacancy\b",
        r"\bwe are hiring\b",
        r"\bjob opening\b",
    ],
}

DEGREE_PATTERNS: dict[str, list[str]] = {
    DegreeLevel.PHD: [r"\bPhD\b", r"\bPh\.D\b", r"\bdoctoral\b", r"\bdoctorate\b"],
    DegreeLevel.MASTERS: [
        r"\bmaster'?s?\b",
        r"\bMSc\b",
        r"\bM\.Sc\b",
        r"\bMS\b",
        r"\bMEng\b",
        r"\bMA\b",
        r"\bMBA\b",
    ],
    DegreeLevel.POSTDOC: [r"\bpostdoc", r"\bpost-doctoral\b"],
    DegreeLevel.CERTIFICATE: [r"\bcertificate\b", r"\bdiploma\b", r"\bmicro-?credential\b"],
}

FUNDING_PATTERNS: dict[str, list[str]] = {
    FundingType.FULLY_FUNDED: [
        r"\bfully.funded\b",
        r"\bfull funding\b",
        r"\bfull scholarship\b",
        r"\bcovers? (all|full) (tuition|costs)\b",
        r"\bfull ride\b",
    ],
    FundingType.TUITION_WAIVER: [
        r"\btuition waiver\b",
        r"\btuition.free\b",
        r"\bwaived tuition\b",
        r"\bno tuition fee",
    ],
    FundingType.STIPEND_ONLY: [r"\bstipend\b", r"\bmonthly allowance\b", r"\bliving allowance\b"],
    FundingType.PARTIAL: [
        r"\bpartial (funding|scholarship)\b",
        r"\bpartially funded\b",
        r"\bup to \d+%\b",
    ],
    FundingType.UNFUNDED: [
        r"\bself.funded\b",
        r"\bunfunded\b",
        r"\bno funding (is )?(available|provided)\b",
    ],
}

INTERNATIONAL_POSITIVE = [
    r"\binternational (students?|applicants?|candidates?)\b",
    r"\bopen to (all nationalities|international)\b",
    r"\bnon-?EU\b",
    r"\bworldwide\b",
    r"\bany nationality\b",
    r"\bF-?1 (visa|students?)\b",
    r"\bvisa sponsorship\b",
]
INTERNATIONAL_NEGATIVE = [
    r"\b(US|U\.S\.) citizens? (or permanent residents? )?only\b",
    r"\bdomestic students? only\b",
    r"\bmust be a (citizen|permanent resident)\b",
    r"\bhome fee status (only|required)\b",
    r"\bno visa sponsorship\b",
    r"\bEU (citizens?|nationals?) only\b",
]

DATE_FORMATS = [
    "%d %B %Y",
    "%d %b %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d.%m.%Y",
    "%d-%m-%Y",
]

DEADLINE_LABEL = re.compile(
    r"(?:application\s+)?(?:deadline|closing date|closes|apply by|due(?:\s+date)?|last date)"
    r"\s*[:\-–]?\s*(?P<value>[^\n\.;|]{4,40})",
    re.IGNORECASE,
)
ROLLING = re.compile(
    r"\b(rolling|open until filled|continuous|ongoing|no deadline|until filled)\b", re.IGNORECASE
)


def _matches(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


# Words that carry no subject information in a course title, so a title made
# only of these tells us nothing about the field.
TITLE_STOPWORDS = {
    "programme", "program", "course", "degree", "masters", "master", "msc",
    "ma", "ms", "meng", "mres", "mphil", "phd", "llm", "online", "learning",
    "full", "part", "time", "joint", "advanced", "applied", "international",
    "and", "the", "of", "in", "for", "with", "study", "studies",
}


def title_is_informative(title: str | None) -> bool:
    """Whether a title says enough to classify on by itself.

    "European Law LLM" is informative and simply out of scope. "Programme
    P-4471" is not informative and its page body is worth reading. Treating
    those the same is what let a law programme's blurb pull it into
    artificial intelligence.
    """
    if not title:
        return False
    words = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", title.lower())
        if word not in TITLE_STOPWORDS
    ]
    return len(words) >= 1


def classify_fields_titled(title: str | None, *body: str | None) -> list[str]:
    """Classify a listing, trusting its title over its body text.

    A programme page carries menus, faculty blurbs and related-course links, so
    classifying on the whole page tagged Law LLMs as artificial intelligence
    and commerce degrees as data science.

    An informative title is therefore authoritative in both directions: what it
    matches, and what it declines to match. The body is read only when the
    title is a code or otherwise says nothing.
    """
    if title_is_informative(title):
        return classify_fields(title)
    return classify_fields(title, *body)


def classify_fields(*texts: str | None) -> list[str]:
    blob = " ".join(t for t in texts if t)
    found = [field for field, patterns in FIELD_PATTERNS.items() if _matches(blob, patterns)]
    # Bare "analytics" also matched by DATA_ANALYTICS is noisy next to a stronger signal.
    if len(found) > 1 and FieldOfStudy.DATA_ANALYTICS in found:
        strong = re.search(
            r"\bdata analytics\b|\bdata analyst\b|\bbusiness intelligence\b", blob, re.IGNORECASE
        )
        if not strong:
            found.remove(FieldOfStudy.DATA_ANALYTICS)
    return found


def classify_type(*texts: str | None, default: str = OpportunityType.GRADUATE_PROGRAM) -> str:
    blob = " ".join(t for t in texts if t)
    # Ordered by specificity: a "PhD scholarship" is a scholarship, not a program.
    for type_ in (
        OpportunityType.SCHOLARSHIP,
        OpportunityType.FELLOWSHIP,
        OpportunityType.ASSISTANTSHIP,
        OpportunityType.RESEARCH_POSITION,
        OpportunityType.INTERNSHIP,
        OpportunityType.GRADUATE_PROGRAM,
        OpportunityType.JOB,
    ):
        if _matches(blob, TYPE_PATTERNS[type_]):
            return type_
    return default


def classify_degrees(*texts: str | None) -> list[str]:
    blob = " ".join(t for t in texts if t)
    return [level for level, patterns in DEGREE_PATTERNS.items() if _matches(blob, patterns)]


def classify_funding(*texts: str | None) -> str:
    blob = " ".join(t for t in texts if t)
    for funding, patterns in FUNDING_PATTERNS.items():
        if _matches(blob, patterns):
            return funding
    return FundingType.UNKNOWN


def detect_international(*texts: str | None) -> bool | None:
    blob = " ".join(t for t in texts if t)
    if _matches(blob, INTERNATIONAL_NEGATIVE):
        return False
    if _matches(blob, INTERNATIONAL_POSITIVE):
        return True
    return None


def parse_date(value: str) -> date | None:
    cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value.strip(), flags=re.IGNORECASE)
    cleaned = cleaned.strip(" ,.;-–—")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    # Day-less forms like "January 2027" resolve to the first of the month.
    for fmt in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def extract_deadline(*texts: str | None) -> tuple[date | None, str | None]:
    """Returns (parsed date, human label). A rolling deadline yields (None, 'Rolling')."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None, None

    for match in DEADLINE_LABEL.finditer(blob):
        raw = match.group("value").strip()
        if ROLLING.search(raw):
            return None, "Rolling"
        parsed = parse_date(raw)
        if parsed:
            return parsed, raw
        # The label may wrap the date in extra words; keep only the date part.
        inner = re.search(r"\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}", raw)
        if inner:
            parsed = parse_date(inner.group(0))
            if parsed:
                return parsed, inner.group(0)

    if ROLLING.search(blob):
        return None, "Rolling"
    return None, None


def content_hash(title: str, url: str, organization: str | None = None) -> str:
    """Stable identity for dedupe: same posting re-crawled must hash the same."""
    normalized_title = re.sub(r"\s+", " ", title.strip().lower())
    normalized_url = url.strip().lower().rstrip("/").split("?")[0]
    normalized_org = (organization or "").strip().lower()
    return hashlib.sha256(
        f"{normalized_title}|{normalized_url}|{normalized_org}".encode()
    ).hexdigest()


def clean_text(value: str | None, limit: int | None = None) -> str:
    """Collapse whitespace and decode HTML entities.

    Feeds routinely serve entity-encoded text (`&#38;`, `&amp;nbsp;`), which would
    otherwise reach the UI verbatim. Unescaping twice handles double-encoded feeds.
    """
    if not value:
        return ""
    cleaned = html.unescape(html.unescape(value))
    cleaned = cleaned.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if limit and len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rsplit(" ", 1)[0] + "…"
    return cleaned
