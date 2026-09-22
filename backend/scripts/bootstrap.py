"""One-off setup helpers.

    python -m scripts.bootstrap keygen
    python -m scripts.bootstrap seed-sources
    python -m scripts.bootstrap make-admin you@example.com
    python -m scripts.bootstrap demo-data
    python -m scripts.bootstrap token you@example.com   # dev-only API token
"""

import argparse
import pathlib
import sys
import uuid
from datetime import UTC, date, datetime, timedelta

from cryptography.fernet import Fernet
from jose import jwt
from sqlalchemy import select

from app.agent.normalize import content_hash
from app.agent.registry import get_adapter
from app.agent.seeds import SEED_SOURCES
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.enums import (
    DegreeLevel,
    FieldOfStudy,
    FundingType,
    OpportunityStatus,
    OpportunityType,
    UserRole,
)
from app.models import Opportunity, OpportunityContact, Profile, Source, User, UserPreference


def keygen() -> None:
    print("TOKEN_ENCRYPTION_KEY=" + Fernet.generate_key().decode())
    print("AUTH_JWT_SECRET=" + uuid.uuid4().hex + uuid.uuid4().hex)
    print("\nCopy AUTH_JWT_SECRET into BOTH backend/.env and frontend/.env.local (as AUTH_SECRET).")


def seed_sources() -> None:
    db = SessionLocal()
    try:
        added = 0
        for entry in SEED_SOURCES:
            if db.scalar(select(Source).where(Source.slug == entry["slug"])):
                continue
            adapter = get_adapter(entry["adapter"])
            db.add(
                Source(
                    slug=entry["slug"],
                    name=entry["name"],
                    kind=entry["kind"],
                    adapter=entry["adapter"],
                    base_url=entry.get("base_url"),
                    config=entry.get("config", {}),
                    enabled=entry.get("enabled", True),
                    requires_credentials=(
                        adapter.requires_credentials if adapter else False
                    ),
                )
            )
            added += 1
        db.commit()
        print(f"Seeded {added} source(s). {len(SEED_SOURCES) - added} already existed.")
        print("HTML-listing sources ship disabled — verify their selectors with:")
        print("  python -m app.agent.probe --url <list_url> --selector <item_selector>")
    finally:
        db.close()


def make_admin(email: str) -> None:
    db = SessionLocal()
    try:
        email = email.lower()
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, full_name=email.split("@")[0], role=UserRole.ADMIN)
            user.profile = Profile(fields_of_study=[], expertise=[])
            user.preference = UserPreference()
            db.add(user)
            print(f"Created {email} as admin.")
        else:
            user.role = UserRole.ADMIN
            print(f"Promoted {email} to admin.")
        db.commit()
    finally:
        db.close()


def dev_token(email: str, hours: int = 24) -> None:
    """Mint an API token without the frontend, for curl and Swagger testing."""
    if settings.environment != "development":
        print("Refusing to mint a token outside development.", file=sys.stderr)
        raise SystemExit(1)

    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.email == email.lower()))
        subject = str(user.id) if user else email.lower()
        name = user.full_name if user else email.split("@")[0]
    finally:
        db.close()

    token = jwt.encode(
        {
            "sub": subject,
            "email": email.lower(),
            "name": name,
            "provider": "dev",
            "iss": settings.auth_jwt_issuer,
            "aud": settings.auth_jwt_audience,
            "exp": int((datetime.now(UTC) + timedelta(hours=hours)).timestamp()),
        },
        settings.auth_jwt_secret,
        algorithm=settings.auth_jwt_algorithm,
    )
    print(token)


DEMO = [
    {
        "title": "PhD Studentship in Machine Learning for Healthcare",
        "organization": "University of Edinburgh",
        "department": "School of Informatics",
        "country": "United Kingdom",
        "location": "Edinburgh, Scotland",
        "type": OpportunityType.ASSISTANTSHIP,
        "fields": [FieldOfStudy.ARTIFICIAL_INTELLIGENCE, FieldOfStudy.COMPUTER_SCIENCE],
        "degrees": [DegreeLevel.PHD],
        "funding": FundingType.FULLY_FUNDED,
        "amount": "Full tuition + £19,237/yr stipend",
        "days": 45,
        "contact": ("Dr. Aoife Brennan", "Principal Investigator", "a.brennan@inf.ed.ac.uk"),
        "description": (
            "A fully funded four-year studentship applying representation learning to "
            "longitudinal electronic health records. Open to international applicants; "
            "the award covers full tuition at the overseas rate plus a stipend at UKRI level."
        ),
    },
    {
        "title": "MSc Data Science — Graduate Scholarship for African Students",
        "organization": "Carnegie Mellon University Africa",
        "country": "Rwanda",
        "location": "Kigali",
        "type": OpportunityType.SCHOLARSHIP,
        "fields": [FieldOfStudy.DATA_SCIENCE, FieldOfStudy.DATA_ANALYTICS],
        "degrees": [DegreeLevel.MASTERS],
        "funding": FundingType.PARTIAL,
        "amount": "Up to 85% tuition",
        "days": 20,
        "contact": ("Admissions Office", "Admissions", "admissions@africa.cmu.edu"),
        "description": (
            "Merit scholarships for the MSc in Information Technology with a data science "
            "concentration. Open to all African nationals. Applications are reviewed on a "
            "rolling basis until the deadline."
        ),
    },
    {
        "title": "Research Assistant — Large Language Model Evaluation",
        "organization": "ETH Zürich",
        "department": "Department of Computer Science",
        "country": "Switzerland",
        "location": "Zürich",
        "type": OpportunityType.RESEARCH_POSITION,
        "fields": [FieldOfStudy.ARTIFICIAL_INTELLIGENCE],
        "degrees": [DegreeLevel.MASTERS, DegreeLevel.PHD],
        "funding": FundingType.STIPEND_ONLY,
        "amount": "CHF 3,500/month",
        "days": 12,
        "contact": ("Prof. Lukas Meier", "Faculty", "lukas.meier@inf.ethz.ch"),
        "description": (
            "Twelve-month research assistantship building evaluation harnesses for "
            "multilingual language models. Visa sponsorship is available for international "
            "candidates."
        ),
    },
    {
        "title": "Data Engineering Graduate Programme",
        "organization": "Zindi / Microsoft Africa Development Centre",
        "country": "Kenya",
        "location": "Nairobi",
        "type": OpportunityType.GRADUATE_PROGRAM,
        "fields": [FieldOfStudy.DATA_ENGINEERING, FieldOfStudy.DATA_SCIENCE],
        "degrees": [DegreeLevel.MASTERS],
        "funding": FundingType.TUITION_WAIVER,
        "days": 75,
        "contact": ("Graduate Programmes Team", "General Enquiries", "grads@example.org"),
        "description": (
            "An 18-month graduate rotation across data platform, streaming and analytics "
            "engineering teams, paired with a part-funded master's placement."
        ),
    },
    {
        "title": "Fulbright Foreign Student Program — Computer Science",
        "organization": "Institute of International Education",
        "country": "United States",
        "type": OpportunityType.SCHOLARSHIP,
        "fields": [FieldOfStudy.COMPUTER_SCIENCE, FieldOfStudy.ARTIFICIAL_INTELLIGENCE],
        "degrees": [DegreeLevel.MASTERS, DegreeLevel.PHD],
        "funding": FundingType.FULLY_FUNDED,
        "amount": "Tuition, living stipend, airfare, health cover",
        "days": 110,
        "contact": ("Fulbright Program Officer", "Scholarship Office", "scholars@example.org"),
        "description": (
            "Fully funded graduate study in the United States for international students. "
            "Applications are submitted through the Fulbright Commission in your home country."
        ),
    },
    {
        "title": "Data Analytics Internship — Summer Cohort",
        "organization": "AmaliTech",
        "country": "Ghana",
        "location": "Takoradi / Accra",
        "type": OpportunityType.INTERNSHIP,
        "fields": [FieldOfStudy.DATA_ANALYTICS],
        "degrees": [DegreeLevel.CERTIFICATE],
        "funding": FundingType.STIPEND_ONLY,
        "days": 30,
        "contact": ("Talent Team", "Recruiter", "talent@example.com"),
        "description": (
            "A twelve-week analytics internship covering SQL, dashboarding and stakeholder "
            "reporting, with a pathway into a graduate analyst role."
        ),
    },
]


def demo_data() -> None:
    db = SessionLocal()
    try:
        created = 0
        for entry in DEMO:
            url = (
                "https://example.org/opportunities/"
                + entry["title"].lower().replace(" ", "-")[:60]
            )
            digest = content_hash(entry["title"], url, entry["organization"])
            if db.scalar(select(Opportunity).where(Opportunity.content_hash == digest)):
                continue

            opportunity = Opportunity(
                title=entry["title"],
                description=entry["description"],
                summary=entry["description"][:200],
                opportunity_type=entry["type"],
                fields_of_study=[str(f) for f in entry["fields"]],
                degree_levels=[str(d) for d in entry["degrees"]],
                organization=entry["organization"],
                department=entry.get("department"),
                location=entry.get("location"),
                country=entry["country"],
                funding_type=entry["funding"],
                funding_amount=entry.get("amount"),
                open_to_international=True,
                application_deadline=date.today() + timedelta(days=entry["days"]),
                url=url,
                source_name="Demo data",
                content_hash=digest,
                status=OpportunityStatus.PUBLISHED,
            )
            db.add(opportunity)
            db.flush()
            name, role, email = entry["contact"]
            db.add(
                OpportunityContact(
                    opportunity_id=opportunity.id,
                    name=name,
                    role=role,
                    email=email,
                    confidence=1.0,
                    is_primary=True,
                    verified=True,
                    source_url=url,
                )
            )
            created += 1
        db.commit()
        print(f"Created {created} demo opportunit{'ies' if created != 1 else 'y'}.")
        if created:
            print(
                "Contact addresses are example.org/example.com placeholders — "
                "safe to test against."
            )
    finally:
        db.close()



# Background media seeded from the Pexels campus set shipped in the repo.
# Once an admin uploads their own, these are just rows they can edit or delete.
SEED_MEDIA = [
    (
        "campus-walk.jpg",
        "Students with backpacks walking a campus path in autumn",
        ["hero", "signin", "community", "gallery"],
        0,
    ),
    (
        "campus-building.jpg",
        "A red-brick university building behind a tree",
        ["hero", "footer", "signin", "gallery"],
        1,
    ),
    (
        "campus-lawn.jpg",
        "Two students studying together on a campus lawn",
        ["hero", "closing", "mentor_card", "gallery"],
        2,
    ),
    (
        "library-study.jpg",
        "A study group gathered around a laptop",
        ["mentor_card", "signin", "gallery"],
        3,
    ),
    (
        "library-celebrate.jpg",
        "Students celebrating together in a library",
        ["closing", "community", "gallery"],
        4,
    ),
    (
        "study-desk.jpg",
        "Notebooks, handwritten notes and coffee on a desk",
        ["footer", "gallery"],
        5,
    ),
]


def seed_media() -> None:
    """Copy the shipped campus photographs into media storage as admin assets."""
    from app.models import MediaAsset
    from app.services import media_storage

    # Lives in this repo, not the frontend: the two deploy separately and the
    # backend must not reach across that boundary.
    source_dir = pathlib.Path(__file__).resolve().parents[1] / "seed_media"
    if not source_dir.exists():
        print(f"No source directory at {source_dir}; nothing to seed.")
        return

    db = SessionLocal()
    added = 0
    try:
        for filename, alt, slots, position in SEED_MEDIA:
            source = source_dir / filename
            if not source.exists():
                print(f"  skip {filename} (not found)")
                continue

            data = source.read_bytes()
            digest = media_storage.content_hash(data)
            if db.scalar(select(MediaAsset).where(MediaAsset.sha256 == digest)):
                continue

            stored = media_storage.save(data, filename, "image/jpeg")
            dimensions = media_storage.image_dimensions(data)
            db.add(
                MediaAsset(
                    filename=filename,
                    content_type="image/jpeg",
                    size_bytes=len(data),
                    sha256=digest,
                    storage_path=stored,
                    kind="image",
                    width=dimensions[0] if dimensions else None,
                    height=dimensions[1] if dimensions else None,
                    title=filename.removesuffix(".jpg").replace("-", " ").title(),
                    alt_text=alt,
                    credit="Pexels — free for commercial use",
                    slots=sorted(slots),
                    position=position,
                    enabled=True,
                )
            )
            added += 1
        db.commit()
        print(f"Seeded {added} media asset(s) into {media_storage.media_root()}.")
        if added:
            print("Manage them at /admin/media once signed in as an admin.")
    finally:
        db.close()



# Accounts for clicking through the app before OAuth is configured.
#
# The domain is a subdomain of example.com, which RFC 2606 reserves for
# documentation: nobody owns it and it can never receive mail. Reserved TLDs
# like .test and .local look like the obvious choice but are rejected by
# email-validator as special-use, so an account on one cannot authenticate.
DEMO_USERS = [
    ("admin@gradportal.example.com", "Ama Boateng", UserRole.ADMIN, True),
    ("mentor@gradportal.example.com", "Kwesi Mensah", UserRole.MENTOR, True),
    ("student@gradportal.example.com", "Efua Owusu", UserRole.STUDENT, False),
]


def demo_users() -> None:
    """Create the accounts the dev sign-in offers."""
    db = SessionLocal()
    try:
        for email, name, role, onboarded in DEMO_USERS:
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email, full_name=name, role=role)
                user.profile = Profile(fields_of_study=[], expertise=[])
                user.preference = UserPreference()
                db.add(user)
                db.flush()
                action = "created"
            else:
                user.role = role
                action = "updated"

            # A generated avatar keeps the required-picture rule satisfied
            # without shipping a photograph of a real person.
            initials = "".join(part[0] for part in name.split()[:2]).upper()
            user.avatar_url = (
                f"https://placehold.co/200x200/1c1c1c/ffffff/png?text={initials}"
            )
            user.onboarding_completed = onboarded

            if onboarded and user.preference is not None:
                user.preference.opportunity_types = [
                    "scholarship",
                    "assistantship",
                    "graduate_program",
                ]
                user.preference.fields_of_study = [
                    "artificial_intelligence",
                    "computer_science",
                    "data_science",
                ]
                user.preference.regions = ["europe", "united_kingdom", "united_states"]
            if user.profile is not None:
                user.profile.country = "Ghana"
                user.profile.headline = (
                    "Community admin"
                    if role == UserRole.ADMIN
                    else "PhD candidate, mentoring applicants"
                    if role == UserRole.MENTOR
                    else "Final-year CS student targeting a funded master's"
                )
                if role == UserRole.MENTOR:
                    user.profile.is_mentor = True
                    user.profile.years_experience = 6
                    user.profile.expertise = ["artificial_intelligence", "data_science"]
                    user.profile.mentor_bio = (
                        "Went through UK and EU admissions in 2021. Happy to talk "
                        "through funding, supervisor emails and visa timing."
                    )
            print(f"  {action:<8} {email:<28} {role}")
        db.commit()
        print()
        print("Sign in as any of these at /signin with ALLOW_DEV_SIGNIN=true.")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="GradPortal bootstrap utilities")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keygen", help="Generate secrets for .env")
    sub.add_parser("seed-sources", help="Insert the starter source catalogue")
    sub.add_parser("demo-data", help="Insert sample opportunities for local development")
    sub.add_parser("seed-media", help="Import the shipped campus photographs as site media")
    sub.add_parser("demo-users", help="Create admin/mentor/student accounts for dev sign-in")
    admin = sub.add_parser("make-admin", help="Promote (or create) a user as admin")
    admin.add_argument("email")
    token = sub.add_parser("token", help="Mint a dev API token")
    token.add_argument("email")
    token.add_argument("--hours", type=int, default=24)

    args = parser.parse_args()
    if args.command == "keygen":
        keygen()
    elif args.command == "seed-sources":
        seed_sources()
    elif args.command == "demo-data":
        demo_data()
    elif args.command == "seed-media":
        seed_media()
    elif args.command == "demo-users":
        demo_users()
    elif args.command == "make-admin":
        make_admin(args.email)
    elif args.command == "token":
        dev_token(args.email, args.hours)


if __name__ == "__main__":
    main()
