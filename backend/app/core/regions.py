"""Region groupings for the country filter.

Applicants think in destinations, not country lists — "somewhere in Europe" is a
real search, "Slovenia OR Portugal OR ..." is not. Each region expands to the
country strings the crawler actually writes onto an opportunity.

The UK is its own region rather than part of Europe: for an international
applicant the fee status, visa route and funding bodies are entirely separate
from the EU, and lumping them together would make the filter useless for the
people it matters most to.
"""

from enum import StrEnum


class Region(StrEnum):
    EUROPE = "europe"
    UNITED_KINGDOM = "united_kingdom"
    UNITED_STATES = "united_states"
    CANADA = "canada"
    AUSTRALIA_NZ = "australia_nz"
    ASIA = "asia"
    AFRICA = "africa"
    MIDDLE_EAST = "middle_east"


REGION_LABELS: dict[str, str] = {
    Region.EUROPE: "Europe",
    Region.UNITED_KINGDOM: "United Kingdom",
    Region.UNITED_STATES: "United States",
    Region.CANADA: "Canada",
    Region.AUSTRALIA_NZ: "Australia & New Zealand",
    Region.ASIA: "Asia",
    Region.AFRICA: "Africa",
    Region.MIDDLE_EAST: "Middle East",
}

# Country strings as they appear on opportunity rows. Aliases are included
# because sources are inconsistent — "USA", "U.S.", "United States of America".
REGION_COUNTRIES: dict[str, list[str]] = {
    Region.EUROPE: [
        "Germany", "Netherlands", "Sweden", "Switzerland", "France", "Belgium",
        "Denmark", "Norway", "Finland", "Austria", "Ireland", "Italy", "Spain",
        "Portugal", "Poland", "Czech Republic", "Czechia", "Hungary", "Greece",
        "Estonia", "Latvia", "Lithuania", "Slovenia", "Slovakia", "Croatia",
        "Romania", "Bulgaria", "Luxembourg", "Iceland", "Cyprus", "Malta",
        "Netherlands (NL)", "Deutschland", "EU", "European Union", "Europe",
    ],
    Region.UNITED_KINGDOM: [
        "United Kingdom", "UK", "U.K.", "England", "Scotland", "Wales",
        "Northern Ireland", "Great Britain",
    ],
    Region.UNITED_STATES: [
        "United States", "United States of America", "USA", "US", "U.S.", "U.S.A.",
    ],
    Region.CANADA: ["Canada"],
    Region.AUSTRALIA_NZ: ["Australia", "New Zealand", "Aotearoa"],
    Region.ASIA: [
        "China", "Japan", "South Korea", "Korea", "Singapore", "Hong Kong",
        "Taiwan", "India", "Malaysia", "Thailand", "Vietnam", "Indonesia",
        "Philippines", "Pakistan", "Bangladesh",
    ],
    Region.AFRICA: [
        "Ghana", "Nigeria", "Kenya", "South Africa", "Rwanda", "Egypt", "Morocco",
        "Tanzania", "Uganda", "Ethiopia", "Senegal", "Tunisia", "Botswana",
        "Zambia", "Zimbabwe", "Cameroon", "Ivory Coast", "Côte d'Ivoire",
    ],
    Region.MIDDLE_EAST: [
        "United Arab Emirates", "UAE", "Saudi Arabia", "Qatar", "Israel",
        "Turkey", "Türkiye", "Jordan", "Kuwait", "Oman", "Bahrain",
    ],
}


def expand_regions(regions: list[str]) -> list[str]:
    """Flatten region keys into the country strings to match against."""
    countries: list[str] = []
    for region in regions:
        countries.extend(REGION_COUNTRIES.get(region, []))
    # Preserve order, drop duplicates.
    seen: set[str] = set()
    return [c for c in countries if not (c in seen or seen.add(c))]


def region_for_country(country: str | None) -> str | None:
    """Reverse lookup, for labelling an opportunity with its region."""
    if not country:
        return None
    needle = country.strip().casefold()
    for region, countries in REGION_COUNTRIES.items():
        if any(needle == c.casefold() for c in countries):
            return region
    return None


def region_options() -> list[dict]:
    return [
        {
            "value": region,
            "label": REGION_LABELS[region],
            "country_count": len(REGION_COUNTRIES[region]),
        }
        for region in Region
    ]
