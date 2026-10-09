# Books Scraper
Scrapes all 1,000 books from books.toscrape.com (title, price, rating, stock, link).

## Sample output
| title | price | rating |
|---|---|---|
| A Light in the Attic | 51.77 | 3 |

## How to run
pip install -r requirements.txt
python scraper.py --max-pages 3

## Features
- Follows "next" pagination with a safety cap
- Retries, timeouts and logging
- Exports CSV and JSON

## Notes
Built for a practice site. Always check robots.txt and terms before scraping.
