# Books Scraper

Scrapes books.toscrape.com (a sandbox site built for practice) and saves title, price, rating, stock status and link for each book. Follows the "next" button through all 50 pages (1,000 books).

## Sample output

| title | price | rating | in_stock |
|---|---|---|---|
| (paste row 1 from your sample_output.csv) | | | |
| (paste row 2) | | | |
| (paste row 3) | | | |

See `sample_output.csv` for 20 rows.

## How to run

```
pip install -r requirements.txt
python books_scraper.py --max-pages 3
```

Options: `--max-pages N`, `--delay SECONDS`, `--details` (also visits each book page for category, UPC and description), `--out NAME`.

## Features

- Follows "next" pagination with a safety cap and loop protection
- Timeouts, automatic retries and logging
- Checks robots.txt before crawling
- Exports CSV and JSON

