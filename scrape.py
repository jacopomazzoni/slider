import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from typing import List, Optional
import re
import requests
import schedule
from bs4 import BeautifulSoup, Tag


DEFAULT_URL = "https://www.binghamton.edu/apps/messaging/announcement/?source=dateline"
from sliderCMS.runtime import DATELINE_PATH

DEFAULT_OUTPUT = DATELINE_PATH
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; DatelineScraper/1.0; +https://example.org/)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


@dataclass
class ForMoreInfo:
    contact_text: Optional[str] = None
    links: List[str] = field(default_factory=list)


@dataclass
class Announcement:
    category: Optional[str]
    title: str
    body: str
    links: List[str]
    for_more_info: Optional[ForMoreInfo] = None
    # Room to grow if you later want timestamps, IDs, etc.


def serialize_announcements(announcements: List[Announcement]) -> List[dict]:
    return [asdict(announcement) for announcement in announcements]


def build_dateline_payload(announcements: List[Announcement], fetched_at: Optional[datetime | str] = None) -> dict:
    if fetched_at is None:
        fetched_at_value = datetime.now(dt_timezone.utc).isoformat()
    elif isinstance(fetched_at, datetime):
        fetched_at_value = fetched_at.isoformat()
    else:
        fetched_at_value = str(fetched_at)

    return {
        "fetched_at": fetched_at_value,
        "announcements": serialize_announcements(announcements),
    }


def normalize_dateline_payload(raw_payload) -> dict:
    if isinstance(raw_payload, list):
        return {
            "fetched_at": None,
            "announcements": raw_payload,
        }

    if isinstance(raw_payload, dict):
        announcements = raw_payload.get("announcements")
        if isinstance(announcements, list):
            return {
                "fetched_at": raw_payload.get("fetched_at"),
                "announcements": announcements,
            }

    return {
        "fetched_at": None,
        "announcements": [],
    }


def get_text_clean(node: Tag) -> str:
    """Extract readable text with reasonable whitespace normalization."""
    text = node.get_text(separator="\n", strip=True)
    # Collapse excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def extract_links(node: Tag) -> List[str]:
    """Return all absolute/relative hrefs found within a node (deduplicated, in order)."""
    seen = set()
    links = []
    for a in node.find_all("a", href=True):
        href = a["href"].strip()
        if href not in seen:
            seen.add(href)
            links.append(href)
    return links


def scrape_dateline(url: str = DEFAULT_URL) -> List[Announcement]:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Heuristic: Work inside the main content area.
    # Try common containers first; fall back to the whole document if not found.
    mainb = soup.find("main")
    if not mainb:
        mainb = soup.find("div", {"id": "content"}) or soup

    announcements: List[Announcement] = []

    current_category: Optional[str] = None
    current_item: Optional[Announcement] = None

    # We iterate over top-level elements inside the main content in order.
    # Categories appear as <h3> (e.g., "Administrative"), while "For More Information" is also <h3>.
    # Announcement titles appear as <h2>.
    content_children = [c for c in mainb.descendants if isinstance(c, Tag) and c.name in {"h2", "h3", "p", "ul", "ol", "div", "section"}]

    i = 0
    while i < len(content_children):
        el = content_children[i]

        # Category header?
        if el.name == "h3":
            h3_text = el.get_text(strip=True)
            # Distinguish category blocks from the "For More Information" subheading
            if h3_text and h3_text.lower() != "for more information:":
                current_category = h3_text
            # If it's "For More Information:" we don't advance category here; it will be parsed when tied to an item.
            i += 1
            continue

        # Announcement title?
        if el.name == "h2":
            # If an item was open, append it before starting a new one
            if current_item:
                announcements.append(current_item)
                current_item = None

            title = el.get_text(strip=True)
            current_item = Announcement(
                category=current_category,
                title=title,
                body="",
                links=[]
            )

            # Collect content until the next <h2> (new announcement) or a new category <h3>
            body_parts: List[str] = []
            body_links: List[str] = []
            for_more_info: Optional[ForMoreInfo] = None

            j = i + 1
            while j < len(content_children):
                nxt = content_children[j]

                # Stop at next announcement title or category header
                if nxt.name == "h2":
                    break
                if nxt.name == "h3":
                    h3_next_text = nxt.get_text(strip=True)
                    if h3_next_text and h3_next_text.lower() != "for more information:":
                        # A new category starts—stop body collection
                        break

                    # It's a "For More Information:" block; parse it specially
                    if h3_next_text.lower() == "for more information:":
                        # Gather "For More Information" paragraph(s)/list(s) that follow until the next h2/h3
                        fmi_links: List[str] = []
                        fmi_text_parts: List[str] = []

                        k = j + 1
                        while k < len(content_children):
                            after = content_children[k]
                            if after.name in {"h2", "h3"}:
                                break
                            # Capture contact line and links
                            fmi_text_parts.append(get_text_clean(after))
                            fmi_links.extend(extract_links(after))
                            k += 1

                        fmi_text = "\n".join([t for t in (t.strip() for t in fmi_text_parts) if t])
                        fmi_text = re.sub(r"\n{3,}", "\n\n", fmi_text)

                        if fmi_text or fmi_links:
                            for_more_info = ForMoreInfo(
                                contact_text=fmi_text if fmi_text else None,
                                links=list(dict.fromkeys(fmi_links))  # dedupe preserving order
                            )
                        # Advance outer pointer to just before k; outer loop will move on
                        j = k
                        continue

                # Otherwise, treat it as part of the announcement body
                body_parts.append(get_text_clean(nxt))
                body_links.extend(extract_links(nxt))
                j += 1

            # Finalize current item’s body and links
            body_text = "\n\n".join([t for t in (t.strip() for t in body_parts) if t])
            current_item.body = body_text
            if body_links:
                # Deduplicate while preserving order
                current_item.links = list(dict.fromkeys(body_links))
            if for_more_info:
                current_item.for_more_info = for_more_info

            # Jump outer index to just before where we stopped
            i = j
            continue

        # Any other element we don't explicitly use at the top level—advance
        i += 1

    # Append the last item if still open
    if current_item:
        announcements.append(current_item)

    return announcements


def write_dateline_json(announcements: List[Announcement], output_path: Path, fetched_at: Optional[datetime | str] = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = build_dateline_payload(announcements, fetched_at=fetched_at)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def run_once(url: str, output_path: Path) -> int:
    try:
        announcements = scrape_dateline(url)
    except requests.RequestException as e:
        print(f"[error] Network/HTTP problem: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[error] Unexpected failure: {e}", file=sys.stderr)
        return 2

    write_dateline_json(announcements, output_path)
    print(f"Wrote {len(announcements)} announcements to {output_path}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scrape Binghamton Dateline announcements into JSON."
    )
    parser.add_argument("-u", "--url", default=DEFAULT_URL, help="Announcements page URL")
    parser.add_argument("-o", "--output", default=DEFAULT_OUTPUT, type=Path, help="Output JSON path")
    parser.add_argument("--watch", action="store_true", help="Run repeatedly instead of once")
    parser.add_argument("--interval-minutes", default=15, type=int, help="Minutes between watched runs")
    args = parser.parse_args(argv)

    if not args.watch:
        return run_once(args.url, args.output)

    if args.interval_minutes < 1:
        print("[error] --interval-minutes must be at least 1", file=sys.stderr)
        return 2

    def job():
        run_once(args.url, args.output)

    job()
    schedule.every(args.interval_minutes).minutes.do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    sys.exit(main())
