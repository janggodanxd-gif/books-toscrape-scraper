"""
Paginated scraper for books.toscrape.com (a sandbox site built for scraping practice).

What it does:
  1. Opens the first listing page.
  2. Pulls title, price, rating, stock status and link for every book on the page.
  3. Follows the "next" button until there isn't one.
  4. (Optional, --details) visits each book's own page for category, UPC and description.
  5. Saves everything to CSV and JSON and prints a summary.

Run:
  pip install requests beautifulsoup4
  python books_scraper.py                    # all 50 pages, about 1 minute
  python books_scraper.py --max-pages 3      # quick test
  python books_scraper.py --details          # also visit all 1,000 book pages (~17 min)
"""

import argparse
import csv
import json
import logging
import re
import time
import urllib.robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

START_URL = "https://books.toscrape.com/"
USER_AGENT = "PortfolioScraper/1.0 (learning project)"

# The site stores ratings as words in the CSS class, e.g. "star-rating Three".
RATINGS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}

LIST_FIELDS = ["title", "price", "rating", "in_stock", "url"]
DETAIL_FIELDS = ["category", "upc", "description"]


# ---------------------------------------------------------------- setup helpers

def make_session():
    """A requests Session with an honest User-Agent and automatic retries."""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    retry = Retry(
        total=5,                                   # up to 5 retries per request
        backoff_factor=1,                          
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,           # obey "wait 30 seconds" if the server says so
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def allowed_by_robots(url):
    """Checking the site's robots.txt for the start URL before crawling."""
    parts = urlparse(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception as e:                         
        logging.warning("Could not read %s (%s); continuing, but check the site's rules yourself.", robots_url, e)
        return True
    return rp.can_fetch(USER_AGENT, url)


def get_soup(session, url):
    """Download a page and return (parsed HTML, final URL after any redirects)."""
    response = session.get(url, timeout=(5, 20))   
    response.raise_for_status()                    
    response.encoding = "utf-8"                    # stops the pound sign turning into garbage
    return BeautifulSoup(response.text, "html.parser"), response.url


# ---------------------------------------------------------------- parsing helpers

def text_or_none(parent, selector):
    tag = parent.select_one(selector)
    return tag.get_text(strip=True) if tag else None


def to_price(text):
    """'£51.77' -> 51.77 ; returns None if there is no number."""
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.]", "", text)         # delete everything except digits and dots
    return float(cleaned) if cleaned else None


def parse_listing(soup, page_url):
    """Turn one listing page into a list of dictionaries (one per book)."""
    rows = []
    for book in soup.select("article.product_pod"):      
        link = book.select_one("h3 a")
        if link is None:                                 
            logging.warning("A book block on %s had no link; skipped.", page_url)
            continue

        rating_tag = book.select_one("p.star-rating")
        rating_word = None
        if rating_tag:
            classes = rating_tag.get("class", [])         
            rating_word = next((c for c in classes if c in RATINGS), None)

        rows.append({
            "title": link.get("title") or link.get_text(strip=True),   # full title is in the attribute
            "price": to_price(text_or_none(book, "p.price_color")),
            "rating": RATINGS.get(rating_word),
            "in_stock": "in stock" in (text_or_none(book, "p.availability") or "").lower(),
            "url": urljoin(page_url, link["href"]),       
        })
    return rows


def find_next_url(soup, page_url):
    """The absolute URL of the 'next' button, or None on the last page."""
    nxt = soup.select_one("li.next a")
    return urljoin(page_url, nxt["href"]) if nxt and nxt.get("href") else None


def parse_detail(soup):
    """Extra fields from a single book's own page."""
    table = {}
    for row in soup.select("table.table-striped tr"):     # a two-column table of facts
        th, td = row.find("th"), row.find("td")
        if th and td:
            table[th.get_text(strip=True)] = td.get_text(strip=True)

    return {
        "category": text_or_none(soup, "ul.breadcrumb li:nth-child(3) a"),
        "upc": table.get("UPC"),
        "description": text_or_none(soup, "#product_description + p"),
    }


# ---------------------------------------------------------------- crawling

def scrape_listings(session, start_url, max_pages, delay):
    """Follow the 'next' link from page to page and collect every book."""
    url = start_url
    books, seen_urls, visited_pages = [], set(), set()
    pages_fetched = 0
    failed_page = None

    while url and pages_fetched < max_pages:               # stop: no next link, or safety cap
        if url in visited_pages:                           # stop: site is sending us in a circle
            logging.warning("Already visited %s; stopping to avoid a loop.", url)
            break
        visited_pages.add(url)

        try:
            soup, final_url = get_soup(session, url)
        except requests.RequestException as e:
            logging.error("Failed to fetch %s: %s", url, e)
            failed_page = url
            break                                         

        page_rows = parse_listing(soup, final_url)
        new_rows = [r for r in page_rows if r["url"] not in seen_urls]   # drop duplicates
        seen_urls.update(r["url"] for r in new_rows)
        books.extend(new_rows)
        pages_fetched += 1
        logging.info("Page %d: %d books (%d total) <- %s", pages_fetched, len(new_rows), len(books), final_url)

        url = find_next_url(soup, final_url)
        if url:
            time.sleep(delay)                              # to be polite between requests

    return books, pages_fetched, failed_page


def add_details(session, books, delay):
    """Visit each book's page and add category, UPC and description to its row."""
    failed = 0
    for i, book in enumerate(books, start=1):
        try:
            soup, _ = get_soup(session, book["url"])
            book.update(parse_detail(soup))
        except requests.RequestException as e:
            logging.error("Detail page failed %s: %s", book["url"], e)
            book.update({f: None for f in DETAIL_FIELDS})   
            failed += 1
        if i % 50 == 0:
            logging.info("Details: %d/%d done", i, len(books))
        time.sleep(delay)
    return failed


# ---------------------------------------------------------------- saving

def save_csv(path, rows, fields):
    # utf-8-sig lets Excel show the pound sign and other symbols correctly
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def save_json(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def summarize(books, pages_fetched, failed_page, fields):
    print("\n--- Summary ---")
    print(f"Pages fetched : {pages_fetched}")
    print(f"Books found   : {len(books)}")
    print(f"Unique URLs   : {len({b['url'] for b in books})}")
    for field in fields:
        missing = sum(1 for b in books if b.get(field) in (None, ""))
        if missing:
            print(f"Missing {field:<11}: {missing}")
    if failed_page:
        print(f"WARNING: stopped early. Failed page: {failed_page}")


# ---------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Scrape books.toscrape.com")
    parser.add_argument("--start-url", default=START_URL)
    parser.add_argument("--max-pages", type=int, default=60, help="safety cap on pages (site has 50)")
    parser.add_argument("--delay", type=float, default=1.0, help="seconds to wait between requests")
    parser.add_argument("--details", action="store_true", help="also visit each book page")
    parser.add_argument("--out", default="books", help="output file name without extension")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not allowed_by_robots(args.start_url):
        logging.error("robots.txt does not allow fetching %s. Stopping.", args.start_url)
        return

    session = make_session()
    books, pages_fetched, failed_page = scrape_listings(session, args.start_url, args.max_pages, args.delay)

    fields = list(LIST_FIELDS)
    if args.details and books:
        add_details(session, books, args.delay)
        fields += DETAIL_FIELDS
        
    save_csv(f"{args.out}.csv", books, fields)
    save_json(f"{args.out}.json", books)
    summarize(books, pages_fetched, failed_page, fields)
    print(f"Saved {args.out}.csv and {args.out}.json")


if __name__ == "__main__":
    main()
