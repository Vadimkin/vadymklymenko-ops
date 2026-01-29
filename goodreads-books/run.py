import json
import logging
import os
import pathlib
import re
import time
from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Page
from enhased_json_decoder import EnhancedJSONEncoder

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

goodreads_base_url = "https://www.goodreads.com"
goodreads_login_url = f"{goodreads_base_url}/user/sign_in"
goodreads_read_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=read&per_page=100"
goodreads_currently_reading_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=currently-reading&per_page=100"
goodreads_own_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=own&per_page=100"
goodreads_bookcrossing_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=bookcrossing&per_page=100"

read_books_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "read.json"
reading_now_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "reading.json"
top_rated_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "top_rated.json"
bookcrossing_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "bookcrossing.json"

GOODREADS_USERNAME = os.environ.get("GOODREADS_USERNAME")
GOODREADS_PASSWORD = os.environ.get("GOODREADS_PASSWORD")


@dataclass
class BookReview:
    title: str
    author: str
    cover_url: str
    review_url: str
    rating: int | None = None
    date_started: datetime.date = None
    date_read: datetime.date = None
    is_reading_now: bool = False
    own: bool = False


def login_to_goodreads(page: Page) -> None:
    """
    Log in to Goodreads using email/password credentials.
    """
    if not GOODREADS_USERNAME or not GOODREADS_PASSWORD:
        raise ValueError("GOODREADS_USERNAME and GOODREADS_PASSWORD environment variables must be set")

    logger.info("Navigating to Goodreads login page...")
    page.goto(goodreads_login_url)

    # Click "Sign in with email" button
    page.click("button.gr-button--dark:has-text('Sign in with email')")

    # Wait for the email form to appear and fill credentials
    page.wait_for_selector("input#ap_email")
    page.fill("input#ap_email", GOODREADS_USERNAME)
    page.fill("input#ap_password", GOODREADS_PASSWORD)

    # Submit the login form
    page.click("input#signInSubmit")

    # Wait for navigation to complete (successful login redirects to home or previous page)
    page.wait_for_load_state("networkidle")

    # Verify login was successful by checking for user menu or similar element
    if "sign_in" in page.url.lower():
        raise Exception("Login failed - still on sign in page")

    logger.info("Successfully logged in to Goodreads")

    # Wait for 10 seconds just in case
    time.sleep(10)


def process_bookshelf_page(page_content: BeautifulSoup, skip_unread: bool = True) -> list[BookReview]:
    books_table = page_content.find('table', id='books')
    books = []

    if not books_table:
        logger.warning("No books table found on page")
        # Print table content
        print(page_content)
        return books

    shelf_header = page_content.find('span', class_='h1Shelf')
    is_current_reading_shelf = shelf_header and "Currently Reading" in shelf_header.text

    for row in books_table.find_all('tr')[1:]:  # skip header
        title_field = row.find('td', class_='field title')
        if not title_field:
            continue

        title_link = title_field.find('a')
        if not title_link:
            continue

        title = title_link.text.strip().replace("\n", " ")

        author_field = row.find('td', class_='field author')
        author = ""
        if author_field:
            author_link = author_field.find('a')
            if author_link:
                author = author_link.text
                if author:
                    # swap first and last name
                    author = " ".join(reversed(author.split(","))).strip()

        cover_url = ""
        img = row.find('img')
        if img and img.get("src"):
            cover_url = img["src"]
            # Replace small cover with big one
            pattern = r"\._S[YX]\d+(_S[YX]\d+)?_\."
            cover_url = re.sub(pattern, ".", cover_url)

        rating_field = row.find('td', class_='field rating')
        rating = None
        if rating_field:
            # Find div with class class="stars", use data-rating property of this field
            rating = len(rating_field.find_all('a', class_='star on')) or None

        date_started = None
        date_started_field = row.find('td', class_='field date_started')
        if date_started_field:
            date_started_value = date_started_field.find('span', class_='date_started_value')
            if date_started_value:
                date_started = date_str_to_date(date_started_value.text)

        date_read = None
        date_read_field = row.find('td', class_='field date_read')
        if date_read_field:
            date_read_value = date_read_field.find('span', class_='date_read_value')
            if date_read_value:
                date_read = date_str_to_date(date_read_value.text)

        if skip_unread and not date_started and not date_read:
            continue

        review_url = ""
        actions_field = row.find('td', class_='field actions')
        if actions_field:
            actions_link = actions_field.find('a', class_='actionLinkLite viewLink nobreak')
            if actions_link and actions_link.get("href"):
                review_url = f"{goodreads_base_url}{actions_link['href']}"

        book = BookReview(
            title=title,
            author=author,
            cover_url=cover_url,
            rating=rating,
            date_started=date_started,
            date_read=date_read,
            review_url=review_url,
            is_reading_now=is_current_reading_shelf
        )

        books.append(book)

    return books


def date_str_to_date(date: str) -> datetime.date:
    """
    Convert date string to datetime

    :param date: Date in string format like Feb 08, 2023 or Feb 2023
    :return: Date instance
    """
    if ", " not in date:
        date_obj = datetime.strptime(date, "%b %Y").replace(day=1)
    else:
        date_obj = datetime.strptime(date, "%b %d, %Y")

    return date_obj.date()


def parse_books(page: Page, url: str, skip_unread: bool = True) -> list[BookReview]:
    """
    Parse books from goodreads using Playwright

    :param page: Playwright page instance
    :param url: Url to parse
    :param skip_unread: Include unread books or not
    :return: List of books
    """
    logger.info("Processing url %s...", url)
    page.goto(url)
    page.wait_for_load_state("networkidle")

    books = []

    # Parse first page
    content = page.content()
    books_page_content = BeautifulSoup(content, 'html.parser')
    books.extend(process_bookshelf_page(books_page_content, skip_unread))

    # Get total books count to calculate pages
    shelf_header = books_page_content.find('span', class_='h1Shelf')
    if shelf_header:
        grey_text = shelf_header.find('span', class_='greyText')
        if grey_text:
            total_books = grey_text.text
            total_books_match = re.search(r"\d+", total_books)
            if total_books_match:
                total_books_int = int(total_books_match.group())
                total_pages = total_books_int // 30 + 1  # 30 books per page

                # Parse remaining pages
                for page_num in range(2, total_pages + 1):
                    page_url = f"{url}&page={page_num}"
                    logger.info("Processing page %d: %s", page_num, page_url)
                    page.goto(page_url)
                    page.wait_for_load_state("networkidle")

                    content = page.content()
                    books_page_content = BeautifulSoup(content, 'html.parser')
                    books.extend(process_bookshelf_page(books_page_content, skip_unread))

    return books


def process():
    """
    Process books from goodreads and write them to file
    """
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=True
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        # Login to Goodreads
        login_to_goodreads(page)

        books = []

        books.extend(parse_books(page, goodreads_currently_reading_first_page_url))
        books.extend(parse_books(page, goodreads_read_first_page_url))

        owning_books = parse_books(page, goodreads_own_first_page_url, skip_unread=False)
        for book in books:
            for owning_book in owning_books:
                if owning_book.title == book.title and owning_book.author == book.author:
                    book.own = True
                    break

        books.sort(key=lambda book: book.date_read or book.date_started, reverse=True)
        # Move currently reading books to the top
        books.sort(key=lambda book: book.is_reading_now, reverse=True)

        logger.info("Books on goodreads: %s", len(books))
        logger.info("Writing books to file...")

        with open(read_books_output_json_file, 'w', encoding='utf-8') as f:
            books_dict = {"books": books}
            json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
            f.write(json_str)

        with open(top_rated_output_json_file, 'w', encoding='utf-8') as f:
            top_rated_books = list(filter(lambda book: book.rating in [4, 5], books))
            books_dict = {"books": top_rated_books}
            json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
            f.write(json_str)

        with open(reading_now_output_json_file, 'w', encoding='utf-8') as f:
            reading_books = list(filter(lambda book: book.is_reading_now, books))
            books_dict = {"books": reading_books}
            json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
            f.write(json_str)

        with open(bookcrossing_output_json_file, 'w', encoding='utf-8') as f:
            bookcrossing_books = parse_books(page, goodreads_bookcrossing_first_page_url, skip_unread=False)
            for book in bookcrossing_books:
                for owning_book in owning_books:
                    if owning_book.title == book.title and owning_book.author == book.author:
                        book.own = True
                        break

            books_dict = {"books": bookcrossing_books}
            json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
            f.write(json_str)

        browser.close()

    logger.info("Done!")


if __name__ == '__main__':
    process()
