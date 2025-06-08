import json
import os
from substack_client import SubstackClient

ignore_substacks = [
    'coderslang',
    '2top',
    'calendracula',
    'andreytemnov',
    'chthonics',
    '2top',
    '2top',
]

def save_profile(subdomain: str, data: dict):
    if not os.path.exists("data"):
        os.makedirs("data")
    with open(f"data/{subdomain}.json", "w") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def is_substack_exists(subdomain: str) -> bool:
    return os.path.exists(f"data/{subdomain}.json")

def is_ukrainian_like_substack(publication: dict) -> bool:
    if any([
        "ы" in (publication.get("author_bio") or "").lower(),
        "ы" in (publication.get("author_name") or "").lower(),
        "ы" in (publication.get("name") or "").lower(),
    ]):
        return False

    return True

if __name__ == "__main__":
    client = SubstackClient()

    popular_words = [
        # "і",
        # "ї",
        "році",
        "населення",
        "також",
        "є",
        "він",
        "років",
        "після",
        "під",
        "під",
        "україна",
        "осіб",
        "який",
        "україни",
        "області",
        "де",
        "складі",
        "особи",
        "історія",
        "їх",
        # Added:
        "своє"
    ]

    for word in popular_words:
        print(f"Processing word: {word}")
        pages = range(100)
        for page in pages:
            posts = client.search_posts(f"\"{word}\"", page=page)
            print(f"Processing page {word}: {page}...")

            for publication in posts["publications"]:
                subdomain = publication["subdomain"]
                if is_substack_exists(subdomain):
                    continue

                if not is_ukrainian_like_substack(publication):
                    continue

                save_profile(subdomain, publication)

            if not posts["more"]:
                break
