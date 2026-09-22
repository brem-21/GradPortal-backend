"""Match opportunities to a user's stated preferences.

Used two ways: to rank the overview feed, and by the ingestion worker to decide
who gets a "new match" notification after a crawl.
"""

from datetime import date, timedelta

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.enums import OpportunityStatus
from app.core.regions import expand_regions, region_for_country
from app.models import Opportunity, User, UserPreference


def preference_filters(preference: UserPreference | None) -> list:
    """Build the WHERE clauses that express a user's saved preferences."""
    if preference is None:
        return []

    clauses = []
    if preference.opportunity_types:
        clauses.append(Opportunity.opportunity_type.in_(preference.opportunity_types))
    if preference.fields_of_study:
        clauses.append(Opportunity.fields_of_study.overlap(preference.fields_of_study))
    if preference.degree_levels:
        clauses.append(
            or_(
                Opportunity.degree_levels.overlap(preference.degree_levels),
                func.cardinality(Opportunity.degree_levels) == 0,
            )
        )
    wanted_countries = list(preference.countries or [])
    wanted_countries.extend(expand_regions(preference.regions or []))
    if wanted_countries:
        clauses.append(
            or_(
                Opportunity.country.in_(wanted_countries),
                Opportunity.is_remote.is_(True),
            )
        )
    if preference.funding_types:
        clauses.append(Opportunity.funding_type.in_(preference.funding_types))
    return clauses


def matching_query(preference: UserPreference | None) -> Select:
    query = select(Opportunity).where(Opportunity.status == OpportunityStatus.PUBLISHED)
    clauses = preference_filters(preference)
    if clauses:
        query = query.where(and_(*clauses))
    return query


def match_score(opportunity: Opportunity, preference: UserPreference | None) -> float:
    """0..1 relevance, weighted toward field overlap and an approaching deadline."""
    if preference is None:
        return 0.0

    score = 0.0
    fields = set(preference.fields_of_study or [])
    if fields:
        overlap = fields & set(opportunity.fields_of_study or [])
        score += 0.45 * (len(overlap) / len(fields))
    if (
        preference.opportunity_types
        and opportunity.opportunity_type in preference.opportunity_types
    ):
        score += 0.2
    if preference.degree_levels and set(preference.degree_levels) & set(
        opportunity.degree_levels or []
    ):
        score += 0.1
    if preference.countries and opportunity.country in preference.countries:
        score += 0.1
    if preference.funding_types and opportunity.funding_type in preference.funding_types:
        score += 0.05

    if opportunity.application_deadline:
        days = (opportunity.application_deadline - date.today()).days
        if 0 <= days <= 60:
            score += 0.1 * (1 - days / 60)
    if any(c.email for c in opportunity.contacts):
        score += 0.05

    return round(min(score, 1.0), 4)


def users_matching(db: Session, opportunity: Opportunity) -> list[User]:
    """Everyone whose preferences this opportunity satisfies, for new-match alerts."""
    query = (
        select(User)
        .join(UserPreference, UserPreference.user_id == User.id)
        .options(selectinload(User.preference))
        .where(User.is_active.is_(True))
    )

    conditions = [
        or_(
            func.cardinality(UserPreference.opportunity_types) == 0,
            UserPreference.opportunity_types.any(opportunity.opportunity_type),
        ),
        or_(
            func.cardinality(UserPreference.fields_of_study) == 0,
            UserPreference.fields_of_study.overlap(opportunity.fields_of_study or []),
        ),
    ]
    if opportunity.country:
        region = region_for_country(opportunity.country)
        location_match = [
            func.cardinality(UserPreference.countries) == 0,
            UserPreference.countries.any(opportunity.country),
        ]
        if region:
            location_match.append(UserPreference.regions.any(region))
        conditions.append(
            or_(
                and_(
                    func.cardinality(UserPreference.countries) == 0,
                    func.cardinality(UserPreference.regions) == 0,
                ),
                *location_match[1:],
            )
        )
    return list(db.scalars(query.where(and_(*conditions))).all())


def closing_soon(db: Session, preference: UserPreference | None, days: int = 7) -> int:
    cutoff = date.today() + timedelta(days=days)
    query = matching_query(preference).where(
        Opportunity.application_deadline.isnot(None),
        Opportunity.application_deadline >= date.today(),
        Opportunity.application_deadline <= cutoff,
    )
    return db.scalar(select(func.count()).select_from(query.subquery())) or 0
