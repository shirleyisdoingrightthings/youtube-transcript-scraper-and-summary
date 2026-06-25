#!/usr/bin/env python3
"""
Fetch YouTube transcript via youtube-transcript.io API
Usage: python3 fetch_transcript.py <youtube_url> [--output <path>]
Output: JSON with video_id, url, title, transcript, duration_seconds, last_timestamp_seconds, coverage, source

完整度校验（防止静默返回半截字幕）：
  抓取后用视频时长 lengthSeconds 与字幕最后一段时间戳做覆盖率校验。
  若主源（youtube-transcript.io）覆盖率 < 90%，自动回退到 youtube-transcript-api
  直连 YouTube 重抓。两源都不达标时，以 error 退出（exit 1），交人工处理，
  绝不把残缺字幕悄悄交给下游。
"""
import sys
import re
import json
import os
import typing
import requests
from dotenv import load_dotenv

load_dotenv()

_token = os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "")
API_AUTH = f"Basic {_token}" if _token else ""

# 覆盖率阈值：字幕末段时间戳须 ≥ 视频时长的 90%，否则判定为残缺
COVERAGE_THRESHOLD = 0.90


def extract_video_id(url: str) -> typing.Optional[str]:
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


def _fmt(start: float, text: str) -> str:
    mins = int(start // 60)
    secs = int(start % 60)
    return f"[{mins:02d}:{secs:02d}] {text}"


def _last_ts(transcript: str) -> float:
    """返回字幕文本里最后一个时间戳对应的秒数（无则 0）。"""
    matches = re.findall(r'\[(\d+):(\d+)\]', transcript)
    if not matches:
        return 0.0
    m, s = matches[-1]
    return int(m) * 60 + int(s)


def fetch_via_io(video_id: str) -> typing.Tuple[str, typing.Optional[int]]:
    """主源：youtube-transcript.io。返回 (transcript_text, duration_seconds)。"""
    resp = requests.post(
        "https://www.youtube-transcript.io/api/transcripts",
        headers={"Authorization": API_AUTH, "Content-Type": "application/json"},
        json={"ids": [video_id]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})

    # 视频时长（用于完整度校验）
    duration = None
    try:
        ls = item["microformat"]["playerMicroformatRenderer"].get("lengthSeconds")
        if ls:
            duration = int(ls)
    except Exception:
        pass

    transcript = ""
    if isinstance(item, dict):
        if item.get("tracks"):
            track = item["tracks"][0]
            segs = track.get("transcript")
            if isinstance(segs, list):
                lines = []
                for seg in segs:
                    text = (seg.get("text") or "").strip()
                    if text:
                        lines.append(_fmt(float(seg.get("start", 0)), text))
                transcript = "\n".join(lines)
        if not transcript:
            for key in ("text", "transcript", "content"):
                if item.get(key):
                    transcript = item[key]
                    break
    return transcript, duration


def fetch_via_ytapi(video_id: str) -> str:
    """回退源：youtube-transcript-api 直连 YouTube。返回 transcript_text。"""
    from youtube_transcript_api import YouTubeTranscriptApi

    # 兼容 1.x 实例式与旧版静态式两种 API
    try:
        raw = YouTubeTranscriptApi().fetch(video_id, languages=["en"]).to_raw_data()
    except AttributeError:
        raw = YouTubeTranscriptApi.get_transcript(video_id, languages=["en"])

    lines = []
    for seg in raw:
        text = (seg.get("text") or "").strip().replace("\n", " ")
        if text:
            lines.append(_fmt(float(seg.get("start", 0)), text))
    return "\n".join(lines)


def main():
    if not API_AUTH or API_AUTH == "Basic ":
        print(json.dumps({"error": "YOUTUBE_TRANSCRIPT_API_KEY not set in .env"}))
        sys.exit(1)

    args = sys.argv[1:]
    output_path = None
    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 >= len(args):
            print(json.dumps({"error": "--output requires a file path"}))
            sys.exit(1)
        output_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if not args:
        print(json.dumps({"error": "Usage: fetch_transcript.py <youtube_url> [--output <path>]"}))
        sys.exit(1)

    url = args[0]
    video_id = extract_video_id(url)
    if not video_id:
        print(json.dumps({"error": f"Cannot extract video ID from: {url}"}))
        sys.exit(1)

    title = get_video_title(video_id)

    # 1) 主源抓取
    duration = None
    source = "youtube-transcript.io"
    try:
        transcript, duration = fetch_via_io(video_id)
    except Exception as e:
        transcript = ""
        print(f"[warn] 主源抓取失败：{e}，尝试回退源 youtube-transcript-api", file=sys.stderr)

    def coverage(tx: str) -> typing.Optional[float]:
        return (_last_ts(tx) / duration) if duration else None

    # 2) 完整度校验：覆盖率不足则自动回退到 youtube-transcript-api
    cov = coverage(transcript)
    incomplete = (cov is not None and cov < COVERAGE_THRESHOLD) or not transcript
    if incomplete:
        reason = (f"覆盖率 {cov:.0%}" if cov is not None else "主源无字幕")
        print(f"[warn] 主源字幕疑似残缺（{reason}），回退到 youtube-transcript-api 直连重抓", file=sys.stderr)
        try:
            fb = fetch_via_ytapi(video_id)
            fb_cov = coverage(fb)
            if (not transcript
                    or (fb_cov is not None and fb_cov > (cov or 0))
                    or (fb_cov is None and len(fb) > len(transcript))):
                transcript, source, cov = fb, "youtube-transcript-api", fb_cov
        except Exception as e:
            print(f"[warn] 回退源抓取失败：{e}", file=sys.stderr)

    last_ts = _last_ts(transcript)

    # 3) 终判：仍残缺则报错退出，绝不把半截字幕交给下游
    if duration and (last_ts / duration) < COVERAGE_THRESHOLD:
        print(json.dumps({
            "error": "字幕不完整，两源均未达完整度阈值，请人工处理",
            "video_id": video_id,
            "title": title,
            "duration_seconds": duration,
            "last_timestamp_seconds": int(last_ts),
            "coverage": round(last_ts / duration, 3),
            "source": source,
        }, ensure_ascii=False))
        sys.exit(1)

    if not transcript:
        print(json.dumps({"error": "未能抓取到任何字幕", "video_id": video_id, "title": title}, ensure_ascii=False))
        sys.exit(1)

    result = json.dumps({
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "original_url": url,
        "title": title,
        "transcript": transcript,
        "duration_seconds": duration,
        "last_timestamp_seconds": int(last_ts),
        "coverage": round(last_ts / duration, 3) if duration else None,
        "source": source,
    }, ensure_ascii=False)

    print(result)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)


if __name__ == "__main__":
    main()
