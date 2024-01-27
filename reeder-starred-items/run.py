import json
import os
import sys
from pathlib import Path
from typing import TypedDict


class ReederItem(TypedDict):
    title: str
    url: str


def parse_shortcuts_payload(payload: str) -> list[ReederItem]:
    # Due to stupidity of Apply Shortcuts, the payload is not a valid array JSON
    # And there is no way to fix it (convert list to array) in Shortcuts
    # It is a JSON with newlines between items
    clean_payload = payload.strip()
    clean_payload = clean_payload.replace("}\n{", '},{').replace('\n', '')
    print(f"Cleaned payload: {clean_payload}")

    posts = json.loads("[" + clean_payload.replace('\n', '') + "]")
    return posts


if __name__ == "__main__":
    stdin = sys.stdin.read()
    payload = parse_shortcuts_payload(stdin)

    current_file_path = os.path.dirname(os.path.abspath(__file__))
    with open(Path(current_file_path) / "reeder-starred-items.json", "w") as f:
        reeder_items = {"items": payload}
        f.write(json.dumps(reeder_items, indent=4))
