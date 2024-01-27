import json
import logging
import pathlib
import grequests
import requests
import re
from dataclasses import dataclass
from datetime import datetime

from bs4 import BeautifulSoup
from enhased_json_decoder import EnhancedJSONEncoder

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

goodreads_base_url = "https://www.goodreads.com"
goodreads_read_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=read"
goodreads_currently_reading_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=currently-reading"
goodreads_own_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=own"
goodreads_bookcrossing_first_page_url = f"{goodreads_base_url}/review/list/18740796-vadym-klymenko?shelf=bookcrossing"

read_books_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "read.json"
top_rated_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "top_rated.json"
bookcrossing_output_json_file = pathlib.Path(__file__).parent.resolve() / "data" / "bookcrossing.json"


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


def process_bookshelf_page(page_content: BeautifulSoup, skip_unread: bool = True) -> list[BookReview]:
    books_table = page_content.find('table', id='books')
    books = []

    is_current_reading_shelf = "Currently Reading" in page_content.find('span', class_='h1Shelf').text

    for row in books_table.find_all('tr')[1:]: # skip header
        title = row.find('td', class_='field title').find('a').text.strip().replace("\n", " ")
        author = row.find('td', class_='field author').find('a').text
        if author:
            # swap first and last name
            author = " ".join(reversed(author.split(","))).strip()

        cover_url = row.find('img')["src"]
        if cover_url:
            # Replace small cover with big one
            # https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1675866212l/106136930._SY75_.jpg
            # https://i.gr-assets.com/images/S/compressed.photo.goodreads.com/books/1566473431l/52283963._SX50_SY75_.jpg
            pattern = r"\._S[YX]\d+(_S[YX]\d+)?_\."
            cover_url = re.sub(pattern, ".", cover_url)
        rating = len(row.find('td', class_='field rating').find_all('span', class_='p10')) or None  # 5 stars = 5 spans

        date_started = row.find('td', class_='field date_started').find('span', class_='date_started_value')
        if date_started:
            date_started = date_str_to_date(date_started.text)

        date_read = row.find('td', class_='field date_read').find('span', class_='date_read_value')
        if date_read:
            date_read = date_str_to_date(date_read.text)

        if skip_unread and not date_started and not date_read:
            # Треба прибрати книжки з Шакалячого експреса :)
            continue

        review_url = row.find('td', class_='field actions').find('a')["href"]
        if review_url:
            review_url = f"{goodreads_base_url}{review_url}"

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


def get_next_page(bs_content: BeautifulSoup) -> str | None:
    has_next_page = bs_content.find('a', class_='next_page')
    if not has_next_page:
        return None
    next_page_url = has_next_page["href"]
    return f"{goodreads_base_url}{next_page_url}"


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


def parse_books(url: str, skip_unread: bool = True) -> list[BookReview]:
    """
    Parse books from goodreads

    :param url: Url to parse
    :param skip_unread: Include unread books or not
    :return: List of books
    """
    logger.info("Processing url %s...", url)
    request = requests.get(url)

    books = []

    books_page_content = BeautifulSoup(request.content, 'html.parser')
    books.extend(process_bookshelf_page(books_page_content, skip_unread))

    total_books = books_page_content.find('span', class_='h1Shelf').find('span', class_='greyText').text
    total_books_int = int(re.search(r"\d+", total_books).group())
    total_pages = total_books_int // 30 + 1  # 30 books per page

    reqs = (grequests.get(f"{url}&page={i}") for i in range(2, total_pages + 1))  # First page is already parsed
    for resp in grequests.map(reqs):
        books_page_content = BeautifulSoup(resp.content, 'html.parser')
        books.extend(process_bookshelf_page(books_page_content, skip_unread))

    return books


def process():
    """
    Process books from goodreads and write them to file
    """
    books = []

    books.extend(parse_books(goodreads_currently_reading_first_page_url))
    books.extend(parse_books(goodreads_read_first_page_url))

    owning_books = parse_books(goodreads_own_first_page_url, skip_unread=False)
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

    with open(bookcrossing_output_json_file, 'w', encoding='utf-8') as f:
        bookcrossing_books = parse_books(goodreads_bookcrossing_first_page_url, skip_unread=False)
        for book in bookcrossing_books:
            for owning_book in owning_books:
                if owning_book.title == book.title and owning_book.author == book.author:
                    book.own = True
                    break

        books_dict = {"books": bookcrossing_books}
        json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
        f.write(json_str)

    logger.info("Done!")


if __name__ == '__main__':
    process()
