"""Selector probe: check an HTML-listing config against the live page before enabling it.

python -m app.agent.probe --url https://example.edu/phd --selector "article.card"
python -m app.agent.probe --url https://example.edu/phd/123 --contacts
"""

import argparse
import asyncio

from selectolax.parser import HTMLParser

from app.agent.contacts import extract_contacts_from_html
from app.agent.http import build_client, fetch_text
from app.agent.normalize import classify_fields, classify_type, clean_text, extract_deadline


async def main() -> None:
    parser = argparse.ArgumentParser(description="Probe a page for listing selectors.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--selector", help="Candidate item_selector to count and preview")
    parser.add_argument("--contacts", action="store_true", help="Run contact extraction")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    async with build_client() as client:
        html = await fetch_text(client, args.url)

    if html is None:
        print(f"✗ Could not fetch {args.url} (blocked by robots.txt, or the request failed)")
        return

    print(f"✓ Fetched {args.url} ({len(html):,} bytes)")
    tree = HTMLParser(html)

    if args.selector:
        nodes = tree.css(args.selector)
        print(f"\nSelector '{args.selector}' matched {len(nodes)} node(s)")
        for node in nodes[: args.limit]:
            heading = node.css_first("h1, h2, h3, h4") or node.css_first("a")
            title = clean_text(heading.text(strip=True)) if heading else "(no heading found)"
            link = node.css_first("a[href]")
            href = link.attributes.get("href") if link else "(no link)"
            body = clean_text(node.text(separator=" ", strip=True), limit=160)
            print(f"\n  • {title}")
            print(f"    link:     {href}")
            print(f"    fields:   {classify_fields(title, body) or '— out of scope'}")
            print(f"    type:     {classify_type(title, body)}")
            deadline, label = extract_deadline(body)
            print(f"    deadline: {deadline or label or '—'}")

    if args.contacts:
        contacts = extract_contacts_from_html(html, args.url)
        print(f"\nContacts found: {len(contacts)}")
        for contact in contacts:
            print(
                f"  • {contact.email}  ({contact.name or 'unnamed'}"
                f" / {contact.role or 'no role'} / confidence {contact.confidence:.2f})"
            )


if __name__ == "__main__":
    asyncio.run(main())
