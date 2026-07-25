import io
import logging
import pathlib
import re
from urllib.request import Request, urlopen

from PIL import Image

logger = logging.getLogger(__name__)

IMAGES_DIR = pathlib.Path(__file__).parent.resolve() / "data" / "images"
GITHUB_IMAGES_BASE_URL = (
    "https://raw.githubusercontent.com/Vadimkin/vadymklymenko-ops/main/goodreads-books/data/images"
)

_BOOK_ID_PATTERN = re.compile(r"/(\d+)\.\w+$")


def _extract_book_id(cover_url: str) -> str | None:
    match = _BOOK_ID_PATTERN.search(cover_url)
    return match.group(1) if match else None


def _cover_image_path(book_id: str) -> pathlib.Path:
    return IMAGES_DIR / f"{book_id}.webp"


def download_cover_image(cover_url: str) -> None:
    """
    Download cover_url and save it as a webp file under data/images.
    Skips the request entirely if a local copy already exists.
    """
    if not cover_url:
        return

    book_id = _extract_book_id(cover_url)
    if not book_id:
        return

    webp_path = _cover_image_path(book_id)
    if webp_path.exists():
        return

    try:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        request = Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=30) as response:
            image_data = response.read()
        image = Image.open(io.BytesIO(image_data))
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        image.save(webp_path, "WEBP")
        logger.info("Downloaded and converted cover image: %s", webp_path.name)
    except Exception as e:
        logger.error("Failed to process cover image %s: %s", cover_url, e)


def process_cover_image(cover_url: str) -> str:
    """
    Look up whether a local webp copy of this cover exists under data/images
    and, if so, return the raw.githubusercontent.com URL pointing to it.

    Makes no network requests - relies only on the local filesystem. Call
    download_cover_image() beforehand to actually fetch missing covers.
    Falls back to the original cover_url if no local copy exists.
    """
    if not cover_url:
        return cover_url

    book_id = _extract_book_id(cover_url)
    if not book_id:
        return cover_url

    webp_path = _cover_image_path(book_id)
    if webp_path.exists():
        return f"{GITHUB_IMAGES_BASE_URL}/{webp_path.name}"

    return cover_url
