import pathlib
import time
from os import listdir
from os.path import isfile, join
from typing import Optional

import feedparser
import dataclasses
import datetime
import json

sixty_days_ago = datetime.datetime.now() - datetime.timedelta(days=30)

substacks_path = pathlib.Path(__file__).parent.resolve() / "substacks"
aggregated_posts_path = pathlib.Path(__file__).parent.resolve() / "export" / "posts.json"
aggregated_blogs_path = pathlib.Path(__file__).parent.resolve() / "export" / "blogs.json"

class EnhancedJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        if isinstance(o, datetime.date):
            return o.isoformat()
        return super().default(o)

def build_substack_blogs():
    feeds = []
    for f in listdir(substacks_path):
        if not isfile(join(substacks_path, f)):
            continue

        with open(join(substacks_path, f), "r") as f:
            file_content = f.read()
            file_json = json.loads(file_content)
            feed_metadata = {
                "feed_url": f"https://{file_json['subdomain']}.substack.com/feed/",
                "logo": file_json["logo_url"],
                "name": file_json["name"],
                "hero_text": file_json["hero_text"],
                "base_url": file_json["base_url"],
            }
            feeds.append(feed_metadata)

    return feeds

def struct_time_to_datetime(st: time.struct_time) -> datetime.datetime:
    """Convert a struct_time to datetime maintaining timezone information when present"""
    tz = None
    if hasattr(st, "tm_gmtoff") and st.tm_gmtoff is not None:
        tz = datetime.timezone(datetime.timedelta(seconds=st.tm_gmtoff))
    # datetime doesn't like leap seconds so just truncate to 59 seconds
    if st.tm_sec in {60, 61}:
        return datetime.datetime(*st[:5], 59, tzinfo=tz)
    return datetime.datetime(*st[:6], tzinfo=tz)

def should_process(entry):
    if not hasattr(entry, "title"):
        return False

    return struct_time_to_datetime(entry.published_parsed) > sixty_days_ago

@dataclasses.dataclass
class FeedEntry():
    channel_title: str
    channel_url: str

    title: str
    url: str
    published: str
    published_parsed: time.struct_time

    channel_logo: Optional[str] = None

    def as_dict(self):
        return {
            "channel_title": self.channel_title,
            "channel_url": self.channel_url,
            "channel_logo": self.channel_logo,
            "title": self.title,
            "url": self.url,
            "published": self.published
        }

def process_feeds():
    blogs = build_substack_blogs()

    entries: list[FeedEntry] = []

    for i, blog in enumerate(blogs):
        print(f"Processing feed {i}/{len(blogs)}: {blog}")
        feed_parsed = feedparser.parse(blog["feed_url"])

        # feed_entries = list(filter(should_process, feed_parsed.entries))[:10]
        feed_entries = list(feed_parsed.entries)[:10]

        feed_entries = [FeedEntry(
            channel_title=feed_parsed.feed.title,
            channel_url=blog["base_url"],
            title=feed_entry.title,
            url=feed_entry.link,
            published=feed_entry.published,
            published_parsed=feed_entry.published_parsed,
            channel_logo=blog["logo"],
        ) for feed_entry in feed_entries]

        entries.extend(feed_entries)

    # Order by date
    entries = sorted(entries, key=lambda entry: entry.published_parsed, reverse=True)
    print("Total entries:", len(entries))

    with open(aggregated_posts_path, 'w', encoding='utf-8') as f:
        books_dict = {"feed": [entry.as_dict() for entry in entries]}
        json_str = json.dumps(books_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=None)
        f.write(json_str)

    with open(aggregated_blogs_path, 'w', encoding='utf-8') as f:
        blogs_dict = {"feed": [blog for blog in blogs]}
        json_str = json.dumps(blogs_dict, cls=EnhancedJSONEncoder, ensure_ascii=False, indent=None)
        f.write(json_str)

if __name__ == "__main__":
    process_feeds()
