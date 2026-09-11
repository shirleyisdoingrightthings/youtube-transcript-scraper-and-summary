#!/usr/bin/env python3
"""
Fetch YouTube transcript via youtube-transcript.io API (付费) 或 youtube-transcript-api (免费直连)
Usage: python3 fetch_transcript.py <youtube_url> [--output <path>] [--prefer-free]
Output: JSON with video_id, url, title, transcript, duration_seconds,
        last_timestamp_seconds, coverage, coverage_verified, source, language

完整度校验（防止静默返回半截字幕）：
  抓取后用视频时长 lengthSeconds 与字幕最后一段时间戳做覆盖率校验。
  某一源覆盖率 < 90% 时自动换用另一源重抓；两源都不达标以 error 退出（exit 1），
  交人工处理，绝不把残缺字幕悄悄交给下游。
  拿不到视频时长时（覆盖率算不出来）不当成通过：输出 coverage_verified=false
  与 warning 字段并在 stderr 告警，由人工确认。

语种校验（防止付费源把非英文轨道错标成 en 静默放行）：
  实例教训：youtube-transcript.io 曾把某视频的阿拉伯语自动翻译轨标成 en 返回，
  覆盖率算出来完全达标（因为内容确实完整，只是文种不对），下游拿到的是一份
  看起来正常、实际不能用的"英文"字幕。付费源返回多条轨道时优先选 languageCode
  以 en 开头的；不管选中哪条，抓到文本后都做一次拉丁字母占比抽检，占比过低则
  判定该源本次抓取失败（抛异常），交上层按"这一源失败，换下一源"的既有逻辑处理，
  不静默放行。

--prefer-free：
  免费源优先，覆盖率达标就收工、完全不碰付费源。付费源免费额度仅 20 视频/月，
  而选题预判每条链接都要抓一次字幕，用这个开关跑预判可以把配额留给真正要做的稿子。
"""
import sys
import re
import json
import os
import typing
import requests
from dotenv import load_dotenv

import http_utils

load_dotenv()

_token = os.environ.get("YOUTUBE_TRANSCRIPT_API_KEY", "")
API_AUTH = f"Basic {_token}" if _token else ""

# 覆盖率阈值：字幕末段时间戳须 ≥ 视频时长的 90%，否则判定为残缺
COVERAGE_THRESHOLD = 0.90

# 语种校验阈值：文本开头样本里，拉丁字母占全部字母字符的比例须 ≥ 此值，
# 否则判定"标注语种与实际内容不符"（防止如阿拉伯语轨被误标成 en 静默放行）。
LATIN_RATIO_THRESHOLD = 0.60


def _latin_ratio(text: str, sample_chars: int = 2000) -> typing.Optional[float]:
    """粗略估计文本样本是否为拉丁字母文字（英文及多数西欧语言）。

    忽略 [MM:SS] 时间戳、空白与标点，只统计字母字符里拉丁字母的占比。
    样本里字母太少（<50 个）时无法判断，返回 None，交调用方按"无法校验"处理，
    不当成通过也不当成失败。
    """
    sample = re.sub(r"\[\d+:\d+(?::\d+)?\]", "", text[:sample_chars])
    letters = [c for c in sample if c.isalpha()]
    if len(letters) < 50:
        return None
    latin = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return latin / len(letters)


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
        resp = http_utils.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=10, label="oembed",
        )
        if resp.ok:
            return resp.json().get("title", "Unknown Title")
    except Exception:
        pass
    return "Unknown Title"


def get_video_duration(video_id: str) -> typing.Optional[int]:
    """备用时长来源：从 YouTube 观看页抓 lengthSeconds。

    主源整体失败（或返回体里没有 microformat）时，duration 会是 None，
    完整度校验就无从做起——那正是本脚本存在的意义被绕过的路径。
    这里免费再取一次时长，尽量不让校验落到"无法判定"。
    """
    try:
        resp = http_utils.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={
                "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=15, label="watch-page",
        )
        if resp.ok:
            m = re.search(r'"lengthSeconds":"(\d+)"', resp.text)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return None


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
    resp = http_utils.post(
        "https://www.youtube-transcript.io/api/transcripts",
        headers={"Authorization": API_AUTH, "Content-Type": "application/json"},
        json={"ids": [video_id]},
        timeout=60, label="youtube-transcript.io",
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
        tracks = item.get("tracks") or []
        if tracks:
            # 多条轨道时优先选 languageCode 以 en 开头的；没有可用的语种字段时
            # 保持原有行为，直接取第一条——真正的安全网是下面的拉丁字母占比检查，
            # 不依赖这里的元数据是否可靠。
            def _is_en(t: dict) -> bool:
                lang = t.get("language") or t.get("languageCode") or t.get("lang") or ""
                return str(lang).lower().startswith("en")

            track = next((t for t in tracks if _is_en(t)), tracks[0])
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

    if transcript:
        ratio = _latin_ratio(transcript)
        if ratio is not None and ratio < LATIN_RATIO_THRESHOLD:
            raise RuntimeError(
                f"疑似语种错标：轨道标注为英文但拉丁字母占比仅 {ratio:.0%}"
                "（可能是非英文自动翻译轨被误标成 en 返回），已判定该源本次抓取失败"
            )
    return transcript, duration


def fetch_via_ytapi(video_id: str) -> typing.Tuple[str, typing.Optional[str]]:
    """免费源：youtube-transcript-api 直连 YouTube。返回 (transcript_text, language_code)。

    不写死英文——非英文视频若只有本国语言字幕，写死 en 会直接抛异常、两源皆废。
    轨道选取顺序：人工字幕优先于自动字幕，英文优先于其他语言。
    """
    from youtube_transcript_api import YouTubeTranscriptApi

    # 兼容 1.x 实例式与旧版静态式两种 API
    try:
        listing = YouTubeTranscriptApi().list(video_id)
    except AttributeError:
        listing = YouTubeTranscriptApi.list_transcripts(video_id)

    tracks = list(listing)
    if not tracks:
        raise RuntimeError("该视频没有任何可用字幕轨")

    def rank(t):
        return (1 if getattr(t, "is_generated", False) else 0,
                0 if (t.language_code or "").startswith("en") else 1)

    track = sorted(tracks, key=rank)[0]
    raw = track.fetch()
    if hasattr(raw, "to_raw_data"):
        raw = raw.to_raw_data()

    lines = []
    for seg in raw:
        text = (seg.get("text") or "").strip().replace("\n", " ")
        if text:
            lines.append(_fmt(float(seg.get("start", 0)), text))
    return "\n".join(lines), track.language_code


def main():
    args = sys.argv[1:]
    output_path = None

    # --prefer-free：免费源优先，够完整就不动付费源（付费源免费额度只有 20 视频/月，
    # 选题预判阶段每条链接都要抓一次，很容易把配额烧在还没决定要做的视频上）
    prefer_free = "--prefer-free" in args
    args = [a for a in args if a != "--prefer-free"]

    if "--output" in args:
        idx = args.index("--output")
        if idx + 1 >= len(args):
            print(json.dumps({"error": "--output requires a file path"}))
            sys.exit(1)
        output_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if not args:
        print(json.dumps({
            "error": "Usage: fetch_transcript.py <youtube_url> [--output <path>] [--prefer-free]"
        }))
        sys.exit(1)

    url = args[0]
    video_id = extract_video_id(url)
    if not video_id:
        print(json.dumps({"error": f"Cannot extract video ID from: {url}"}))
        sys.exit(1)

    title = get_video_title(video_id)

    duration = None
    state = {"transcript": "", "source": "", "language": None, "coverage": None}

    def coverage(tx: str) -> typing.Optional[float]:
        return (_last_ts(tx) / duration) if duration else None

    def take(tx: str, src: str, lang: typing.Optional[str]) -> typing.Optional[float]:
        """收下一份候选字幕，比现有的更完整才替换，返回它的覆盖率"""
        nonlocal duration
        # 时长要在校验之前就位：付费源抛异常或返回体缺 microformat 时 duration 为 None，
        # 覆盖率算不出来，"残缺则换源"会整个失效（半截字幕反而一路放行）
        if not duration:
            duration = get_video_duration(video_id)
        cov = coverage(tx)
        cur, cur_cov = state["transcript"], state["coverage"]
        better = (not cur
                  or (cov is not None and cov > (cur_cov or 0))
                  or (cov is None and cur_cov is None and len(tx) > len(cur)))
        if better:
            state.update(transcript=tx, source=src, language=lang, coverage=cov)
        return cov

    def fetch_paid() -> typing.Optional[float]:
        nonlocal duration
        if not API_AUTH or API_AUTH == "Basic ":
            raise RuntimeError("YOUTUBE_TRANSCRIPT_API_KEY 未配置，跳过付费源")
        tx, dur = fetch_via_io(video_id)
        if dur:
            duration = dur
        return take(tx, "youtube-transcript.io", None)

    def fetch_free() -> typing.Optional[float]:
        tx, lang = fetch_via_ytapi(video_id)
        return take(tx, "youtube-transcript-api", lang)

    # 1) 抓取：默认付费源优先（稳定性更好）；--prefer-free 时免费源优先（省配额）。
    #    前一个源够完整就直接收工，不再动下一个源。
    order = ([("免费源 youtube-transcript-api", fetch_free), ("付费源 youtube-transcript.io", fetch_paid)]
             if prefer_free else
             [("付费源 youtube-transcript.io", fetch_paid), ("免费源 youtube-transcript-api", fetch_free)])

    for idx, (name, fetcher) in enumerate(order):
        try:
            cov = fetcher()
        except Exception as e:
            print(f"[warn] {name}抓取失败：{e}", file=sys.stderr)
            continue
        if cov is not None and cov >= COVERAGE_THRESHOLD:
            if idx == 0 and prefer_free:
                print(f"[info] {name}覆盖率 {cov:.0%}，已达标，本次不消耗付费源配额", file=sys.stderr)
            break
        if idx < len(order) - 1:
            reason = (f"覆盖率 {cov:.0%}" if cov is not None else
                      ("无字幕" if not state["transcript"] else "完整度无法校验"))
            print(f"[warn] {name}字幕疑似残缺（{reason}），换用{order[idx + 1][0]}重抓", file=sys.stderr)

    transcript, source = state["transcript"], state["source"]
    last_ts = _last_ts(transcript)

    if not transcript:
        print(json.dumps({
            "error": "两源均未能抓取到任何字幕（若付费源被跳过，请检查 .env 的 YOUTUBE_TRANSCRIPT_API_KEY）",
            "video_id": video_id,
            "title": title,
        }, ensure_ascii=False))
        sys.exit(1)

    # 3) 终判：仍残缺则报错退出，绝不把半截字幕交给下游
    final_cov = (last_ts / duration) if duration else None

    if final_cov is not None and final_cov < COVERAGE_THRESHOLD:
        print(json.dumps({
            "error": "字幕不完整，两源均未达完整度阈值，请人工处理",
            "video_id": video_id,
            "title": title,
            "duration_seconds": duration,
            "last_timestamp_seconds": int(last_ts),
            "coverage": round(final_cov, 3),
            "coverage_verified": True,
            "source": source,
        }, ensure_ascii=False))
        sys.exit(1)

    # 补抓后仍拿不到时长：完整度无法校验，必须显式告警交人工确认，不得静默当成通过
    if final_cov is None:
        print("[warn] 拿不到视频时长，本次无法校验字幕完整度（coverage_verified=false），"
              "请人工比对视频时长与字幕末段时间戳后再决定是否使用", file=sys.stderr)

    result = json.dumps({
        "video_id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "original_url": url,
        "title": title,
        "transcript": transcript,
        "duration_seconds": duration,
        "last_timestamp_seconds": int(last_ts),
        "coverage": round(final_cov, 3) if final_cov is not None else None,
        "coverage_verified": final_cov is not None,
        "warning": None if final_cov is not None else "无法获取视频时长，完整度未经校验，请人工确认",
        "source": source,
        "language": state["language"],
    }, ensure_ascii=False)

    print(result)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result)


if __name__ == "__main__":
    main()
