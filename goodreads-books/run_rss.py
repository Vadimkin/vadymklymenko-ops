import json
import logging
import os
import pathlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from urllib.request import urlopen, Request

from enhased_json_decoder import EnhancedJSONEncoder

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Configuration
GOODREADS_USER_ID = "18740796"
GOODREADS_RSS_KEY = os.environ.get("GOODREADS_RSS_KEY")

RSS_BASE_URL = f"https://www.goodreads.com/review/list_rss/{GOODREADS_USER_ID}"

# Output files
data_dir = pathlib.Path(__file__).parent.resolve() / "data"
read_books_output_json_file = data_dir / "read.json"
reading_now_output_json_file = data_dir / "reading.json"
top_rated_output_json_file = data_dir / "top_rated.json"
bookcrossing_output_json_file = data_dir / "bookcrossing.json"


@dataclass
class BookReview:
    title: str
    author: str
    cover_url: str
    review_url: str
    rating: int | None = None
    date_started: date = None
    date_read: date = None
    is_reading_now: bool = False
    own: bool = False


def build_rss_url(shelf: str, page: int = 1) -> str:
    """Build RSS feed URL for a specific shelf and page."""
    return f"{RSS_BASE_URL}?key={GOODREADS_RSS_KEY}&shelf={shelf}&page={page}"


def fetch_rss(url: str) -> str:
    """Fetch RSS feed content from URL."""
    logger.debug("Fetching RSS: %s", url)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def parse_rfc2822_date(date_str: str) -> date | None:
    """Parse RFC 2822 date string to date object."""
    if not date_str or not date_str.strip():
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.date()
    except (ValueError, TypeError):
        return None


def parse_book_from_item(item: ET.Element, is_currently_reading: bool = False) -> BookReview | None:
    """Parse a single book item from RSS XML."""

    def get_text(tag: str) -> str:
        elem = item.find(tag)
        return elem.text.strip() if elem is not None and elem.text else ""

    title = get_text("title")
    if not title:
        return None

    author = get_text("author_name")

    # Get cover URL - prefer large, fallback to medium, then regular
    cover_url = get_text("book_large_image_url")
    if not cover_url or "nophoto" in cover_url:
        cover_url = get_text("book_medium_image_url")
    if not cover_url or "nophoto" in cover_url:
        cover_url = get_text("book_image_url")

    # Clean up cover URL - remove size modifiers for highest quality
    if cover_url:
        pattern = r"\._S[YX]\d+(_S[YX]\d+)?_\."
        cover_url = re.sub(pattern, ".", cover_url)

    review_url = get_text("link")
    # Remove query params from review URL
    if "?" in review_url:
        review_url = review_url.split("?")[0]

    # Parse rating (0 means unrated)
    rating_str = get_text("user_rating")
    rating = int(rating_str) if rating_str and rating_str != "0" else None

    # Parse dates
    date_read = parse_rfc2822_date(get_text("user_read_at"))

    # FIXME There is no field like that
    date_started = parse_rfc2822_date(get_text("user_read_at"))

    # Check if book is owned (from user_shelves)
    user_shelves = get_text("user_shelves")
    own = "own" in user_shelves.lower().split(", ") if user_shelves else False

    return BookReview(
        title=title,
        author=author,
        cover_url=cover_url,
        review_url=review_url,
        rating=rating,
        date_started=date_started,
        date_read=date_read,
        is_reading_now=is_currently_reading,
        own=own,
    )


def fetch_shelf(shelf: str, is_currently_reading: bool = False, skip_unread: bool = True) -> list[BookReview]:
    """
    Fetch all books from a shelf, handling pagination.

    Args:
        shelf: Shelf name (read, currently-reading, own, bookcrossing, etc.)
        is_currently_reading: Mark books as currently reading
        skip_unread: Skip books without date_read or date_started

    Returns:
        List of BookReview objects
    """
    books = []
    page = 1

    while True:
        url = build_rss_url(shelf, page)
        logger.info("Fetching shelf '%s' page %d...", shelf, page)

        try:
            content = fetch_rss(url)
        except Exception as e:
            logger.error("Failed to fetch page %d: %s", page, e)
            break

        root = ET.fromstring(content)
        items = root.findall(".//item")

        if not items:
            logger.info("No more items on page %d, stopping", page)
            break

        logger.info("Found %d items on page %d", len(items), page)

        for item in items:
            book = parse_book_from_item(item, is_currently_reading)
            if book:
                if skip_unread and not book.date_started and not book.date_read:
                    continue
                books.append(book)

        page += 1

        # Safety limit
        if page > 50:
            logger.warning("Reached page limit, stopping")
            break

    return books


def fetch_read_shelf() -> list[BookReview]:
    """Fetch books from the 'read' shelf."""
    logger.info("=" * 50)
    logger.info("FETCHING READ SHELF")
    logger.info("=" * 50)
    books = fetch_shelf("read", is_currently_reading=False, skip_unread=True)
    logger.info("Total read books: %d", len(books))
    return books


def fetch_currently_reading_shelf() -> list[BookReview]:
    """Fetch books from the 'currently-reading' shelf."""
    logger.info("=" * 50)
    logger.info("FETCHING CURRENTLY-READING SHELF")
    logger.info("=" * 50)
    books = fetch_shelf("currently-reading", is_currently_reading=True, skip_unread=False)
    logger.info("Total currently reading books: %d", len(books))
    return books


def fetch_own_shelf() -> list[BookReview]:
    """Fetch books from the 'own' shelf."""
    logger.info("=" * 50)
    logger.info("FETCHING OWN SHELF")
    logger.info("=" * 50)
    books = fetch_shelf("own", is_currently_reading=False, skip_unread=False)
    logger.info("Total owned books: %d", len(books))
    return books


def fetch_bookcrossing_shelf() -> list[BookReview]:
    """Fetch books from the 'bookcrossing' shelf."""
    logger.info("=" * 50)
    logger.info("FETCHING BOOKCROSSING SHELF")
    logger.info("=" * 50)
    books = fetch_shelf("bookcrossing", is_currently_reading=False, skip_unread=False)
    logger.info("Total bookcrossing books: %d", len(books))
    return books


def mark_owned_books(books: list[BookReview], owned_books: list[BookReview]) -> None:
    """Mark books as owned if they appear in the owned_books list."""
    owned_set = {(b.title, b.author) for b in owned_books}
    for book in books:
        if (book.title, book.author) in owned_set:
            book.own = True


def save_books(books: list[BookReview], filepath: pathlib.Path) -> None:
    """Save books to JSON file."""
    with open(filepath, "w", encoding="utf-8") as f:
        books_dict = {"books": books}
        json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
        f.write(json_str)
    logger.info("Saved %d books to %s", len(books), filepath.name)


def process():
    """Process all shelves and save to JSON files."""
    # Fetch each shelf separately for debugging
    currently_reading = fetch_currently_reading_shelf()
    read_books = fetch_read_shelf()
    owned_books = fetch_own_shelf()
    bookcrossing_books = fetch_bookcrossing_shelf()

    # Combine currently reading and read books
    all_books = currently_reading + read_books

    # Mark ownership
    mark_owned_books(all_books, owned_books)
    mark_owned_books(bookcrossing_books, owned_books)

    # Sort: by date (newest first), then currently reading at top
    all_books.sort(key=lambda b: b.date_read or b.date_started or date.min, reverse=True)
    all_books.sort(key=lambda b: b.is_reading_now, reverse=True)

    logger.info("=" * 50)
    logger.info("SAVING OUTPUT FILES")
    logger.info("=" * 50)

    # Save all read/reading books
    save_books(all_books, read_books_output_json_file)

    # Save top rated (4-5 stars)
    top_rated = [b for b in all_books if b.rating in (4, 5)]
    save_books(top_rated, top_rated_output_json_file)

    # Save currently reading
    reading_only = [b for b in all_books if b.is_reading_now]
    save_books(reading_only, reading_now_output_json_file)

    # Save bookcrossing
    save_books(bookcrossing_books, bookcrossing_output_json_file)

    logger.info("Done!")


if __name__ == "__main__":
    process()
