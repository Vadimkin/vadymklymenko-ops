import json
import pathlib
import time
import datetime

import feedparser

from enhased_json_encoder import EnhancedJSONEncoder

blogroll_json_path = pathlib.Path(__file__).parent.resolve() / "data" / "blogroll.json"


def clean_entry(entry):
    return {
        "title": entry.title,
        "link": entry.link,
        "published": entry.published,
    }


def main():
    twenty_days_ago = datetime.datetime.now() - datetime.timedelta(days=20)

    feeds = [
        "https://sinja.io/rss",
        "https://mrgall.com/feed/",
        "https://www.govorukhin.com/blog/rss.xml",
        "https://poohitan.com/rss",
        # "https://rsshub.app/paulgraham/articles",
        "https://zemlan.in/rss.xml",
        "https://ciechanow.ski/atom.xml",
        "https://leonid.shevtsov.me/stendap/index.xml",
        "https://toytakeorg.substack.com/feed/",
        "https://zametkin.me/feed/",
        "https://blog.alexkolodko.com/rss/",
        "https://world.hey.com/dhh/feed.atom",
        "https://world.hey.com/jason/feed.atom",
        "https://moretothat.com/feed/",
        "https://www.autodidacts.io/rss/",
        "https://snyder.substack.com/feed",
        "https://waitbutwhy.com/feed",
        "https://reporters.media/feed/",
    ]

    entries = []
    for feed_url in feeds:
        print("Processing feed:", feed_url)
        feed = feedparser.parse(feed_url)
        feed_entries = filter(lambda entry: struct_time_to_datetime(entry.published_parsed) > twenty_days_ago, feed.entries)
        entries.extend(list(feed_entries)[:10])

    # Order by date
    entries = sorted(entries, key=lambda entry: entry.published_parsed, reverse=True)
    clean_entries = [clean_entry(entry) for entry in entries]

    with open(blogroll_json_path, 'w', encoding='utf-8') as f:
        books_dict = {"feed": clean_entries}
        json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=2)
        f.write(json_str)


def struct_time_to_datetime(st: time.struct_time) -> datetime.datetime:
    """Convert a struct_time to datetime maintaining timezone information when present"""
    tz = None
    if hasattr(st, "tm_gmtoff") and st.tm_gmtoff is not None:
        tz = datetime.timezone(datetime.timedelta(seconds=st.tm_gmtoff))
    # datetime doesn't like leap seconds so just truncate to 59 seconds
    if st.tm_sec in {60, 61}:
        return datetime.datetime(*st[:5], 59, tzinfo=tz)
    return datetime.datetime(*st[:6], tzinfo=tz)


if __name__ == "__main__":
    main()
