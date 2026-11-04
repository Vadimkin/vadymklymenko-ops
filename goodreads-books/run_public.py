"""
Update book data from public Goodreads pages (no login, no RSS).

Goodreads stopped serving the keyless shelf RSS (404 since 2026-10-28), and the
shelf list pages require sign-in. What is still public:

* Profile page /user/show/USER_ID - the "Currently Reading" block has title,
  author, book id, cover, shelves and a progress percent (when one was posted).
  It shows at most 3 books.
* Grid widget /review/grid_widget/USER_ID?shelf=... - title, review link and
  cover for any shelf. Used for the full currently-reading list and "up next".
* Book page /book/show/BOOK_ID - used to fill in the author of a new book.

Rules:
* Never wipe saved data: if a fetch fails or the expected block is missing,
  the previous file contents are kept.
* A card without a progress percent keeps the last saved percent.
* read.json keeps its previously saved finished books (they cannot be fetched
  publicly any more); only the currently-reading part on top is refreshed.
"""

import html
import json
import logging
import pathlib
import re
from dataclasses import dataclass, fields
from datetime import date, datetime
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from enhased_json_decoder import EnhancedJSONEncoder
from image_utils import download_cover_image, process_cover_image

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

GOODREADS_USER_ID = "18740796"
BASE_URL = "https://www.goodreads.com"
PROFILE_URL = f"{BASE_URL}/user/show/{GOODREADS_USER_ID}"
GRID_WIDGET_URL = f"{BASE_URL}/review/grid_widget/{GOODREADS_USER_ID}"
UP_NEXT_COUNT = 8

# An empty User-Agent gets a 403, so pretend to be a regular browser.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

data_dir = pathlib.Path(__file__).parent.resolve() / "data"
read_books_output_json_file = data_dir / "read.json"
reading_now_output_json_file = data_dir / "reading.json"
top_rated_output_json_file = data_dir / "top_rated.json"
up_next_output_json_file = data_dir / "up_next.json"

COVER_SIZE_PATTERN = re.compile(r"\._S[YX]\d+(_S[YX]\d+)?_\.")
COVER_BOOK_ID_PATTERN = re.compile(r"/(\d+)\.\w+$")
REVIEW_ID_PATTERN = re.compile(r"/review/show/(\d+)")
BOOK_ID_PATTERN = re.compile(r"/book/show/(\d+)")
PERCENT_PATTERN = re.compile(r"(\d{1,3})\s*%")


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
    progress: int | None = None


@dataclass
class GridBook:
    title: str
    review_url: str
    cover_url: str


# ---------------------------------------------------------------- helpers


def fetch(url: str) -> str:
    logger.debug("Fetching %s", url)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def review_url_from_href(href: str) -> str:
    match = REVIEW_ID_PATTERN.search(href)
    return f"{BASE_URL}/review/show/{match.group(1)}" if match else ""


def full_size_cover(cover_url: str) -> str:
    """Drop the size modifier (._SX50_.) so Goodreads serves the full cover."""
    return COVER_SIZE_PATTERN.sub(".", cover_url) if cover_url else ""


def store_cover(cover_url: str) -> str:
    """Save the cover under data/images and return its GitHub URL."""
    cover_url = full_size_cover(cover_url)
    if cover_url:
        download_cover_image(cover_url)
        cover_url = process_cover_image(cover_url)
    return cover_url


def book_id_from_cover(cover_url: str) -> str | None:
    match = COVER_BOOK_ID_PATTERN.search(full_size_cover(cover_url))
    return match.group(1) if match else None


def parse_timestamp(value: str) -> date | None:
    """Parse 'Sep 12, 2026 04:12AM' (or 'Sep 12, 2026') into a date."""
    for fmt in ("%b %d, %Y %I:%M%p", "%b %d, %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def load_books(filepath: pathlib.Path) -> list[BookReview]:
    if not filepath.exists():
        return []
    with open(filepath, encoding="utf-8") as f:
        raw_books = json.load(f).get("books", [])
    known_fields = {f.name for f in fields(BookReview)}
    books = []
    for raw in raw_books:
        raw = {k: v for k, v in raw.items() if k in known_fields}
        for key in ("date_started", "date_read"):
            if raw.get(key):
                raw[key] = date.fromisoformat(raw[key])
        books.append(BookReview(**raw))
    return books


def save_books(books: list[BookReview], filepath: pathlib.Path) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json_str = json.dumps({"books": books}, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
        f.write(json_str + "\n")
    logger.info("Saved %d books to %s", len(books), filepath.name)


def fetch_author_from_book_page(book_id: str | None) -> str:
    """Read the author name from the public book page (JSON-LD)."""
    if not book_id:
        return ""
    try:
        content = fetch(f"{BASE_URL}/book/show/{book_id}")
    except Exception as e:
        logger.warning("Failed to fetch book page %s: %s", book_id, e)
        return ""
    soup = BeautifulSoup(content, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        authors = data.get("author") if isinstance(data, dict) else None
        if isinstance(authors, dict):
            authors = [authors]
        # The list also holds translators and editors; the first is the author.
        if authors and authors[0].get("name"):
            return authors[0]["name"]
    name = soup.select_one(".ContributorLink__name")
    return name.get_text(strip=True) if name else ""


# ---------------------------------------------------------------- sources


def fetch_grid_widget(shelf: str, num_books: int) -> list[GridBook]:
    """
    Fetch a shelf through the old grid widget. It returns a JavaScript snippet
    with the HTML in a string literal: `var widget_code = '...'`.
    """
    url = f"{GRID_WIDGET_URL}?shelf={shelf}&sort=date_added&order=d&num_books={num_books}"
    content = fetch(url)
    match = re.search(r"var widget_code = '(.*?)'\s*\n", content, re.S)
    if not match:
        raise ValueError(f"No widget_code in grid widget response for shelf {shelf}")

    # Undo JS string escaping: \" \' \/ \n
    widget_html = re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1), match.group(1))
    soup = BeautifulSoup(widget_html, "html.parser")

    books = []
    for container in soup.select("div.gr_grid_book_container"):
        link = container.find("a")
        img = container.find("img")
        if not link:
            continue
        books.append(
            GridBook(
                title=html.unescape(link.get("title", "")).strip(),
                review_url=review_url_from_href(link.get("href", "")),
                cover_url=img.get("src", "") if img else "",
            )
        )
    return books


def fetch_profile_reading_cards() -> dict[str, dict]:
    """
    Parse the "Currently Reading" block on the public profile.
    Returns cards keyed by review URL. Raises if the block is missing.
    """
    soup = BeautifulSoup(fetch(PROFILE_URL), "html.parser")
    box = soup.find(id="currentlyReadingReviews")
    if box is None:
        raise ValueError("No currently-reading block on profile page")

    cards = {}
    for update in box.select("div.Updates"):
        title_link = update.select_one("a.bookTitle")
        timestamp = update.select_one("a.updatedTimestamp")
        if not title_link or not timestamp:
            continue

        review_url = review_url_from_href(timestamp.get("href", ""))
        if not review_url:
            continue

        author_link = update.select_one("a.authorName")
        cover = update.select_one(".firstcol img")
        book_id = BOOK_ID_PATTERN.search(title_link.get("href", ""))
        shelves = [a.get_text(strip=True) for a in update.select("a.actionLinkLite")]

        # Progress is printed in the card text, e.g. "page 54 of 320 (16%)".
        # Drop the "want to read" / rating widget before searching.
        text_root = update.select_one(".whos-review") or update
        percents = [int(p) for p in PERCENT_PATTERN.findall(text_root.get_text(" "))]
        percents = [p for p in percents if 0 <= p <= 100]

        cards[review_url] = {
            "title": title_link.get_text(strip=True),
            "author": author_link.get_text(strip=True) if author_link else "",
            "book_id": book_id.group(1) if book_id else None,
            "cover_url": cover.get("src", "") if cover else "",
            "own": "own" in shelves,
            "date_started": parse_timestamp(timestamp.get_text()),
            "progress": percents[-1] if percents else None,
        }
    return cards


# ---------------------------------------------------------------- shelves


def build_currently_reading(previous: list[BookReview]) -> list[BookReview]:
    """
    The grid widget gives the full ordered list; the profile cards (max 3)
    add author, ownership, start date and progress.
    """
    cards = fetch_profile_reading_cards()
    grid = fetch_grid_widget("currently-reading", 20)
    previous_by_url = {b.review_url: b for b in previous}
    logger.info("Profile cards: %d, grid books: %d", len(cards), len(grid))

    books = []
    for item in grid:
        card = cards.get(item.review_url, {})
        prev = previous_by_url.get(item.review_url)
        cover_source = card.get("cover_url") or item.cover_url

        author = card.get("author") or (prev.author if prev else "")
        if not author:
            author = fetch_author_from_book_page(card.get("book_id") or book_id_from_cover(cover_source))

        progress = card.get("progress")
        if progress is None and prev:
            progress = prev.progress

        books.append(
            BookReview(
                title=card.get("title") or item.title,
                author=author,
                cover_url=store_cover(cover_source),
                review_url=item.review_url,
                rating=prev.rating if prev else None,
                # The card timestamp moves with progress updates, so keep the
                # first date we saw.
                date_started=(prev.date_started if prev and prev.date_started else card.get("date_started")),
                is_reading_now=True,
                own=card["own"] if card else (prev.own if prev else False),
                progress=progress,
            )
        )

    # Newest started first, same order as before.
    books.sort(key=lambda b: b.date_started or date.min, reverse=True)
    return books


def build_up_next(previous: list[BookReview]) -> list[BookReview]:
    grid = fetch_grid_widget("to-read", UP_NEXT_COUNT)[:UP_NEXT_COUNT]
    previous_by_url = {b.review_url: b for b in previous}

    books = []
    for item in grid:
        prev = previous_by_url.get(item.review_url)
        author = prev.author if prev and prev.author else fetch_author_from_book_page(book_id_from_cover(item.cover_url))
        books.append(
            BookReview(
                title=item.title,
                author=author,
                cover_url=store_cover(item.cover_url),
                review_url=item.review_url,
                own=prev.own if prev else False,
            )
        )
    return books


def process():
    previous_read = load_books(read_books_output_json_file)
    previous_reading = load_books(reading_now_output_json_file)
    previous_up_next = load_books(up_next_output_json_file)

    try:
        reading = build_currently_reading(previous_reading)
        if not reading:
            raise ValueError("Currently-reading list came back empty")
        save_books(reading, reading_now_output_json_file)
    except Exception as e:
        logger.error("Keeping previous currently-reading shelf: %s", e)
        reading = previous_reading

    # Finished books can't be fetched publicly, so keep the saved ones and
    # only refresh the currently-reading part at the top.
    reading_urls = {b.review_url for b in reading}
    finished = [b for b in previous_read if not b.is_reading_now and b.review_url not in reading_urls]
    all_books = reading + finished
    save_books(all_books, read_books_output_json_file)
    save_books([b for b in all_books if b.rating in (4, 5)], top_rated_output_json_file)

    try:
        up_next = build_up_next(previous_up_next)
        if not up_next:
            raise ValueError("Up next list came back empty")
        save_books(up_next, up_next_output_json_file)
    except Exception as e:
        logger.error("Keeping previous up next shelf: %s", e)

    logger.info("Done!")


if __name__ == "__main__":
    process()
