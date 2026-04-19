#!/usr/bin/env python3
"""
Fetch YouTube transcript via youtube-transcript.io API
Usage: python3 fetch_transcript.py <youtube_url>
Output: JSON with video_id, url, title, transcript
"""
import sys
import re
import json
import os
import requests
from dotenv import load_dotenv

load_dotenv()

_token = os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "")
API_AUTH = f"Basic {_token}" if _token else ""


def extract_video_id(url: str) -> str | None:
    url = url.strip()
    patterns = [
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
        r'[?&]v=([a-zA-Z0-9_-]{11})',
        r'/embed/([a-zA-Z0-9_-]{11})',
        r'/v/([a-zA-Z0-9_-]{11})',
        r'/shorts/([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def get_video_title(video_id: str) -> str:
    try:
        resp = requests.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("title", "Unknown Title")
    except Exception:
        pass
    return "Unknown Title"


def fetch_transcript(video_id: str) -> str:
    resp = requests.post(
        "https://www.youtube-transcript.io/api/transcripts",
        headers={
            "Authorization": API_AUTH,
            "Content-Type": "application/json",
        },
        json={"ids": [video_id]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    # API returns a list of transcript objects
    if isinstance(data, list) and data:
        item = data[0]
        if isinstance(item, dict):
            # Try common field names
            for key in ("text", "transcript", "content"):
                if item.get(key):
                    return item[key]
            # Some APIs return segments as list of {text, start, duration}
            if "segments" in item:
                return " ".join(
                    seg.get("text", "") for seg in item["segments"]
                )
        return str(item)
    elif isinstance(data, dict):
        for key in ("text", "transcript", "content"):
            if data.get(key):
                return data[key]
    return str(data)


def main():
    if not API_AUTH or API_AUTH == "Basic ":
        print(json.dumps({"error": "YOUTUBE_TRANSCRIPT_API_KEY not set in .env"}))
        sys.exit(1)
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: fetch_transcript.py <youtube_url>"}))
        sys.exit(1)

    url = sys.argv[1]
    video_id = extract_video_id(url)

    if not video_id:
        print(json.dumps({"error": f"Cannot extract video ID from: {url}"}))
        sys.exit(1)

    title = get_video_title(video_id)

    try:
        transcript = fetch_transcript(video_id)
    except Exception as e:
        print(json.dumps({"error": f"Transcript fetch failed: {e}"}))
        sys.exit(1)

    print(json.dumps({
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "original_url": url,
        "title": title,
        "transcript": transcript,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
