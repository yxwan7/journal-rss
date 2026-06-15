import os
import re
import time
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

import requests
import yaml


OUTPUT_DIR = "docs"
ROWS_PER_JOURNAL = 30
CROSSREF_MAILTO = os.environ.get("CROSSREF_MAILTO", "").strip()


def safe_text(value, fallback=""):
    if value is None:
        return fallback
    return str(value)


def normalize_slug(slug):
    slug = slug.lower().strip()
    slug = re.sub(r"[^a-z0-9\-]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


def crossref_date_to_datetime(item):
    candidates = [
        item.get("published-online"),
        item.get("published-print"),
        item.get("published"),
        item.get("created"),
        item.get("deposited"),
    ]

    for candidate in candidates:
        if not candidate:
            continue

        date_parts = candidate.get("date-parts")
        if not date_parts or not date_parts[0]:
            continue

        parts = date_parts[0]

        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) >= 2 else 1
            day = int(parts[2]) if len(parts) >= 3 else 1
            return datetime(year, month, day, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue

    return datetime.now(timezone.utc)


def get_title(item):
    titles = item.get("title") or []
    if titles:
        return safe_text(titles[0], "Untitled")
    return "Untitled"


def get_author_names(item, max_authors=8):
    authors = item.get("author") or []
    names = []

    for author in authors[:max_authors]:
        given = author.get("given", "")
        family = author.get("family", "")
        name = f"{given} {family}".strip()
        if name:
            names.append(name)

    return names


def get_authors(item, max_authors=8):
    names = get_author_names(item, max_authors=max_authors)
    if len(item.get("author") or []) > max_authors:
        names.append("et al.")

    return ", ".join(names)


def get_doi_link(item):
    doi = item.get("DOI")
    if doi:
        return f"https://doi.org/{doi}"
    return item.get("URL", "")


def get_abstract(item):
    abstract = item.get("abstract", "")
    if not abstract:
        return ""

    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return abstract


def build_rss(journal, items):
    journal_name = journal["name"]
    homepage = journal.get("homepage", "")
    now = datetime.now(timezone.utc)

    rss_items = []

    for item in items:
        title = get_title(item)
        link = get_doi_link(item)
        doi = item.get("DOI", link)
        author_names = get_author_names(item)
        authors = get_authors(item)
        abstract = get_abstract(item)
        pub_dt = crossref_date_to_datetime(item)
        dc_creators = "".join(
            f"\n      <dc:creator>{escape(author)}</dc:creator>"
            for author in author_names
        )

        description_parts = []
        if authors:
            description_parts.append(f"Authors: {authors}")
        if abstract:
            description_parts.append(abstract)

        description = "\n\n".join(description_parts)

        rss_items.append(f"""
    <item>
      <title>{escape(title)}</title>
      <link>{escape(link)}</link>
      <guid isPermaLink="false">{escape(doi)}</guid>
{dc_creators}
      <pubDate>{format_datetime(pub_dt)}</pubDate>
      <description>{escape(description)}</description>
    </item>""")

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>{escape(journal_name)} Latest Articles</title>
    <link>{escape(homepage)}</link>
    <description>Latest journal articles for {escape(journal_name)}</description>
    <language>en</language>
    <lastBuildDate>{format_datetime(now)}</lastBuildDate>
{''.join(rss_items)}
  </channel>
</rss>
"""


def fetch_crossref_items(issn):
    url = f"https://api.crossref.org/journals/{issn}/works"
    params = {
        "filter": "type:journal-article",
        "sort": "published",
        "order": "desc",
        "rows": ROWS_PER_JOURNAL,
    }

    user_agent = "journal-rss-generator/1.0"
    if CROSSREF_MAILTO:
        params["mailto"] = CROSSREF_MAILTO
        user_agent = f"{user_agent} (mailto:{CROSSREF_MAILTO})"

    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": user_agent},
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    return data["message"]["items"]


def write_index(journals):
    links = []

    for journal in journals:
        slug = normalize_slug(journal["slug"])
        name = journal["name"]
        links.append(f'<li><a href="{slug}.xml">{escape(name)}</a></li>')

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Journal RSS Feeds</title>
</head>
<body>
  <h1>Journal RSS Feeds</h1>
  <ul>
    {''.join(links)}
  </ul>
</body>
</html>
"""

    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def load_journals():
    with open("journals.yml", "r", encoding="utf-8") as f:
        journals = yaml.safe_load(f)

    if not isinstance(journals, list):
        raise ValueError("journals.yml must contain a list of journals")

    return journals


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    journals = load_journals()

    for journal in journals:
        name = journal["name"]
        issn = journal["issn"]
        slug = normalize_slug(journal["slug"])

        print(f"Fetching {name} ({issn})...")

        try:
            items = fetch_crossref_items(issn)
            rss = build_rss(journal, items)

            output_path = os.path.join(OUTPUT_DIR, f"{slug}.xml")
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(rss)

            print(f"Generated {output_path}")
            time.sleep(1)
        except Exception as error:
            print(f"Failed to generate feed for {name}: {error}")

    write_index(journals)


if __name__ == "__main__":
    main()
