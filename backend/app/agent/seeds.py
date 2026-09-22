"""Starter source catalogue.

Every entry below is annotated with its verification state as of 2026-09-22:

  VERIFIED  the URL was fetched and parsed successfully; ships enabled.
  BLOCKED   the host returns 403 to non-browser clients (Cloudflare or similar).
            Ships disabled. Enabling it needs either a published feed URL from
            the site owner or a partnership — not a spoofed user agent.
  UNVERIFIED  plausible selectors that were never confirmed against the live
            page. Ships disabled. Confirm before enabling:

    python -m app.agent.probe --url <list_url> --selector <item_selector>

Adding a source is a database row, not a code change — use the admin sources
screen, or extend this list and re-run `python -m scripts.bootstrap seed-sources`.
"""

from app.core.enums import DegreeLevel, OpportunityType, SourceKind

SEED_SOURCES: list[dict] = [
    # ---------------- Feeds ----------------
    {
        # VERIFIED 2026-09-22 — 10 entries parsed. Scholarships, fellowships and
        # graduate programmes aimed at African and international applicants.
        "slug": "opportunity-desk",
        "name": "Opportunity Desk — scholarships & fellowships",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "rss_feed",
        "base_url": "https://opportunitydesk.org",
        "enabled": True,
        "config": {
            "feed_url": "https://opportunitydesk.org/feed/",
            "type_hint": None,
            "fetch_detail": True,
            "max_items": 30,
        },
    },
    {
        # VERIFIED 2026-09-22 — 10 entries parsed.
        "slug": "opportunities-for-africans",
        "name": "Opportunities For Africans",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "rss_feed",
        "base_url": "https://www.opportunitiesforafricans.com",
        "enabled": True,
        "config": {
            "feed_url": "https://www.opportunitiesforafricans.com/feed/",
            "type_hint": None,
            "fetch_detail": True,
            "max_items": 30,
        },
    },
    {
        # BLOCKED 2026-09-22 — 403 to non-browser clients. EURAXESS publishes an
        # open API; swap this to the json_api adapter once you register for a key.
        "slug": "euraxess-research-jobs",
        "name": "EURAXESS — European research positions",
        "kind": SourceKind.JOB_BOARD,
        "adapter": "rss_feed",
        "base_url": "https://euraxess.ec.europa.eu",
        "enabled": False,
        "config": {
            "feed_url": "https://euraxess.ec.europa.eu/jobs/search/rss",
            "type_hint": OpportunityType.RESEARCH_POSITION,
            "fetch_detail": True,
            "max_items": 40,
        },
    },
    {
        # BLOCKED 2026-09-22 — the /rss path returns the HTML page, not a feed.
        "slug": "nature-careers",
        "name": "Nature Careers",
        "kind": SourceKind.JOB_BOARD,
        "adapter": "rss_feed",
        "base_url": "https://www.nature.com/naturecareers",
        "enabled": False,
        "config": {
            "feed_url": "https://www.nature.com/naturecareers/jobs/rss",
            "type_hint": OpportunityType.RESEARCH_POSITION,
            "fetch_detail": True,
            "max_items": 40,
        },
    },
    {
        # BLOCKED 2026-09-22 — Cloudflare challenge (403).
        "slug": "findaphd-computer-science",
        "name": "FindAPhD — Computer Science",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "rss_feed",
        "base_url": "https://www.findaphd.com",
        "enabled": False,
        "config": {
            "feed_url": "https://www.findaphd.com/phds/computer-science/?01w0&Rss=1",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "degree_hint": [DegreeLevel.PHD],
            "fetch_detail": True,
            "max_items": 50,
        },
    },


    # ---------------- Universities (VERIFIED against the live pages) ----------------
    #
    # Selectors below were confirmed with `python -m app.agent.probe` on
    # 2026-09-22 and the match counts recorded. Course catalogues list every
    # programme a university offers, so `max_items` is set high enough to reach
    # the whole list and `prefilter_by_title` then drops everything outside the
    # five fields *before* any detail page is fetched.
    {
        # VERIFIED — 279 programmes matched. Drupal views listing, stable markup.
        "slug": "edinburgh-postgraduate-taught",
        "name": "University of Edinburgh — taught postgraduate degrees",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "html_listing",
        "base_url": "https://www.ed.ac.uk",
        "enabled": True,
        "config": {
            "list_url": (
                "https://www.ed.ac.uk/studying/postgraduate/degrees"
                "?r=site/taught&edition=2026&sid=&cw_xml=search.php"
            ),
            "item_selector": "div.views-row",
            "organization": "University of Edinburgh",
            "country": "United Kingdom",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "degree_hint": [DegreeLevel.MASTERS],
            "prefilter_by_title": True,
            "fetch_detail": True,
            "max_items": 400,
        },
    },
    {
        # VERIFIED — 92 programmes matched.
        "slug": "kth-master-programmes",
        "name": "KTH Royal Institute of Technology — master's programmes",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "html_listing",
        "base_url": "https://www.kth.se",
        "enabled": True,
        "config": {
            "list_url": "https://www.kth.se/en/studies/master/programmes",
            "item_selector": "div.block.list li",
            "organization": "KTH Royal Institute of Technology",
            "country": "Sweden",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "degree_hint": [DegreeLevel.MASTERS],
            "prefilter_by_title": True,
            "fetch_detail": True,
            "max_items": 150,
        },
    },
    {
        # VERIFIED — 29 programmes matched.
        "slug": "epfl-master-programs",
        "name": "EPFL — master's programmes",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "html_listing",
        "base_url": "https://www.epfl.ch",
        "enabled": True,
        "config": {
            "list_url": "https://www.epfl.ch/education/master/programs/",
            "item_selector": "div.col-sm-6.col-xl-4",
            "organization": "EPFL",
            "country": "Switzerland",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "degree_hint": [DegreeLevel.MASTERS],
            "prefilter_by_title": True,
            "fetch_detail": True,
            "max_items": 60,
        },
    },

    {
        # VERIFIED — 33 programmes matched. The list mixes undergraduate and
        # graduate study, so bachelor's and minors are excluded by title.
        "slug": "georgia-tech-computing",
        "name": "Georgia Tech — College of Computing degrees",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "html_listing",
        "base_url": "https://www.cc.gatech.edu",
        "enabled": True,
        "config": {
            "list_url": "https://www.cc.gatech.edu/degree-programs/",
            "item_selector": "div.views-field-title",
            "organization": "Georgia Institute of Technology",
            "country": "United States",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "title_exclude": [
                r"\bbachelor\b",
                r"\bB\.S\.",
                r"\bundergraduate\b",
                r"\bminor\b",
                r"\bcertificate\b",
            ],
            "prefilter_by_title": True,
            "fetch_detail": True,
            "max_items": 60,
        },
    },
    {
        # VERIFIED — 23 cards matched; the marketing ones carry no field in
        # their title and are dropped by the scope prefilter.
        "slug": "northeastern-khoury",
        "name": "Northeastern — Khoury College of Computer Sciences",
        "kind": SourceKind.UNIVERSITY,
        "adapter": "html_listing",
        "base_url": "https://www.khoury.northeastern.edu",
        "enabled": True,
        "config": {
            "list_url": "https://www.khoury.northeastern.edu/programs/",
            "item_selector": "div.standard-card__content",
            "title_selector": "h3.standard-card__title",
            "organization": "Northeastern University",
            "country": "United States",
            "type_hint": OpportunityType.GRADUATE_PROGRAM,
            "degree_hint": [DegreeLevel.MASTERS],
            "title_exclude": [r"\bbachelor\b", r"\bBS in\b", r"\bPhD\b.*\bapply\b"],
            "prefilter_by_title": True,
            "fetch_detail": True,
            "max_items": 40,
        },
    },

    # ---------------- HTML listings (UNVERIFIED selectors — probe, then enable) ----------------
    {
        "slug": "daad-scholarship-database",
        "name": "DAAD Scholarship Database (Germany)",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "html_listing",
        "base_url": "https://www2.daad.de",
        "enabled": False,
        "config": {
            "list_url": "https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/",
            "item_selector": ".c-list-item, article.result",
            "title_selector": "h3, .c-list-item__title",
            "summary_selector": ".c-list-item__text, p",
            "organization": "DAAD",
            "country": "Germany",
            "type_hint": OpportunityType.SCHOLARSHIP,
            "fetch_detail": True,
        },
    },
    {
        "slug": "chevening-scholarships",
        "name": "Chevening Scholarships (UK)",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "html_listing",
        "base_url": "https://www.chevening.org",
        "enabled": False,
        "config": {
            "list_url": "https://www.chevening.org/scholarships/",
            "item_selector": "article, .card",
            "organization": "Chevening (UK FCDO)",
            "country": "United Kingdom",
            "type_hint": OpportunityType.SCHOLARSHIP,
            "degree_hint": [DegreeLevel.MASTERS],
            "fetch_detail": True,
        },
    },
    {
        "slug": "commonwealth-scholarships",
        "name": "Commonwealth Scholarship Commission (UK)",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "html_listing",
        "base_url": "https://cscuk.fcdo.gov.uk",
        "enabled": False,
        "config": {
            "list_url": "https://cscuk.fcdo.gov.uk/scholarships/",
            "item_selector": "article, .scholarship-listing li",
            "organization": "Commonwealth Scholarship Commission",
            "country": "United Kingdom",
            "type_hint": OpportunityType.SCHOLARSHIP,
            "fetch_detail": True,
        },
    },
    {
        "slug": "mastercard-foundation-scholars",
        "name": "Mastercard Foundation Scholars Program",
        "kind": SourceKind.SCHOLARSHIP_PORTAL,
        "adapter": "html_listing",
        "base_url": "https://mastercardfdn.org",
        "enabled": False,
        "config": {
            "list_url": "https://mastercardfdn.org/all/scholars/",
            "item_selector": "article, .card",
            "organization": "Mastercard Foundation",
            "type_hint": OpportunityType.SCHOLARSHIP,
            "fetch_detail": True,
        },
    },
    # ---------------- Credential-gated ----------------
    {
        "slug": "linkedin-graduate-ai",
        "name": "LinkedIn — graduate & AI research roles (partner API)",
        "kind": SourceKind.LINKEDIN,
        "adapter": "linkedin",
        "base_url": "https://www.linkedin.com",
        "enabled": True,
        "requires_credentials": True,
        "config": {
            "keywords": "graduate research assistant artificial intelligence data science",
            "count": 25,
            "type_hint": OpportunityType.RESEARCH_POSITION,
        },
    },
    {
        "slug": "handshake-institution",
        "name": "Handshake — institution feed",
        "kind": SourceKind.HANDSHAKE,
        "adapter": "handshake",
        "base_url": "https://app.joinhandshake.com",
        "enabled": True,
        "requires_credentials": True,
        "config": {"per_page": 50, "type_hint": OpportunityType.INTERNSHIP},
    },
]
