#!/usr/bin/env python3
"""精编稿体检：时间戳单调递增校验 + 时间轴缺口扫描。

Usage:
    python3 check_transcript_edit.py <成品.md> [--transcript <transcript.json>]
                                     [--min-gap 120] [--json]

为什么要有这个脚本：
    精编压缩最危险的失败模式不是删多了几句，而是**整段关键问答被静默删掉、
    自检时还看不出来**——成品读起来依然连贯。实例：某期 72 分钟访谈的精编初稿
    静默删掉了 [50:22–52:54]，那是全片唯一正面回答标题主线的问答；同轮还删掉了
    嘉宾的让步段，使其立场比原话更硬。两处都是靠交付前的 Agent Council 才捞回来。
    靠模型自觉扫描不可靠，交给脚本算。

它做什么、不做什么：
    ✅ 算出所有 ≥2 分钟的删除区间，并把该区间的原字幕摘出来，逐条列成待办；
    ✅ 标出时间戳逆序（成品里时间倒流 = 硬伤）；
    ✅ 把含让步 / 限定语（of course、that said、当然、不过…）的删除区间标为高风险
       ——这类删除会让嘉宾立场比原话更硬，属于扭曲；
    ❌ 不替你判断"这段该不该删"。理由只能落在四类（广告口播 / 铺垫性长问 /
       重复论证 / 纯附和回合），由人或 Agent 逐条认领，见
       skills/dialogue_transcript.md「删减红线：时间轴缺口扫描」。

退出码：
    0 = 没有逆序（可能仍有待认领的缺口，清单打印在上面）
    1 = 存在时间戳逆序，或参数 / 文件有误
"""
from __future__ import annotations

import json
import os
import re
import sys

TIMESTAMP_RE = re.compile(r"\[(\d{1,3}):([0-5]\d)\]")
DEFAULT_MIN_GAP = 120          # 秒，与 skill 的「≥2 分钟」一致

# 让步 / 限定 / 自我收口的信号词：这些句子被删掉会让立场比原话更硬
HEDGE_MARKERS = (
    "of course", "to be fair", "that said", "with that said", "however",
    "although", "though ", "on the other hand", "granted", "admittedly",
    "i don't deny", "i do not deny", "i'm not saying", "i am not saying",
    "not always", "there are exceptions", "caveat", "i could be wrong",
    "it depends", "当然", "不过", "话说回来", "我不否认", "也有例外",
    "未必", "并不是说", "话虽如此",
)


def fmt(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def parse_timestamps(text: str) -> list:
    """抽出文本里的所有 [MM:SS]，返回 [(秒, 行内位置)] 列表，保持出现顺序。"""
    out = []
    for m in TIMESTAMP_RE.finditer(text):
        out.append((int(m.group(1)) * 60 + int(m.group(2)), m.start()))
    return out


def parse_transcript(transcript: str) -> list:
    """把 `[MM:SS] 正文` 的字幕解析成 [(秒, 正文)]。"""
    segments = []
    for line in transcript.splitlines():
        m = TIMESTAMP_RE.match(line.strip())
        if m:
            sec = int(m.group(1)) * 60 + int(m.group(2))
            segments.append((sec, line.strip()[m.end():].strip()))
    return segments


def slice_text(segments: list, start: int, end: int, limit: int = 220) -> str:
    """取 (start, end) 区间内的原字幕，拼成一段摘录。"""
    picked = [t for s, t in segments if start < s < end]
    joined = " ".join(picked)
    return joined[:limit] + ("…" if len(joined) > limit else "")


def has_hedge(text: str) -> bool:
    low = text.lower()
    return any(marker in low for marker in HEDGE_MARKERS)


def find_reversals(stamps: list) -> list:
    """时间戳逆序：成品里时间倒流，属于硬伤。"""
    reversals = []
    for i in range(1, len(stamps)):
        prev, cur = stamps[i - 1][0], stamps[i][0]
        if cur < prev:
            reversals.append({"index": i, "prev": prev, "cur": cur})
    return reversals


def find_gaps(stamps: list, segments: list, duration: int | None,
              min_gap: int) -> list:
    """扫出所有 ≥ min_gap 的删除区间（含开场与片尾）。"""
    kept = sorted({s for s, _ in stamps})
    gaps = []

    if kept and kept[0] >= min_gap:
        gaps.append({"kind": "开场", "start": 0, "end": kept[0]})

    for a, b in zip(kept, kept[1:]):
        if b - a >= min_gap:
            gaps.append({"kind": "中段", "start": a, "end": b})

    if duration and kept and duration - kept[-1] >= min_gap:
        gaps.append({"kind": "片尾", "start": kept[-1], "end": duration})

    for g in gaps:
        excerpt = slice_text(segments, g["start"], g["end"])
        g["seconds"] = g["end"] - g["start"]
        g["excerpt"] = excerpt
        g["hedge"] = has_hedge(excerpt)
    return gaps


def sentence_rhythm(text: str) -> dict:
    """句长节奏统计（借鉴 shuorenhua「节奏单调」与 Humanizer-zh「连续三句同长」）。

    AI 文本的句长比人写的均匀得多，读起来"平、没有呼吸感"。这里只报数、不判分：
    变异系数（标准差 / 均值）越低越平；三连同长是更直观的局部信号。
    """
    body = []
    for line in text.split("\n"):
        s = line.strip()
        if not s or s[0] in "#>-|`" or s.startswith(("🖼", "🎞", "📊", "👩", "🧑", "📍", "💡", "🎙", "👤", "**")):
            continue
        body.append(re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]", "", s))
    lens = [len(re.findall(r"[\u4e00-\u9fff]", s))
            for s in re.split(r"[。！？]", "\n".join(body)) if len(s.strip()) > 4]
    lens = [n for n in lens if n >= 5]
    if len(lens) < 10:
        return {}
    mean = sum(lens) / len(lens)
    var = sum((n - mean) ** 2 for n in lens) / len(lens)
    sd = var ** 0.5
    runs = sum(1 for i in range(len(lens) - 2)
               if max(lens[i:i + 3]) - min(lens[i:i + 3]) <= 0.15 * (sum(lens[i:i + 3]) / 3))
    return {"sentences": len(lens), "mean": round(mean, 1),
            "sd": round(sd, 1), "cv": round(sd / mean, 2), "flat_runs": runs}


def locate_transcript(md_path: str) -> str | None:
    """成品与 transcript.json 同属归档三件套，默认在同目录找。"""
    folder = os.path.dirname(os.path.abspath(md_path))
    candidates = [f for f in sorted(os.listdir(folder))
                  if f.startswith("transcript") and f.endswith(".json")]
    return os.path.join(folder, candidates[0]) if candidates else None


def report(md_path: str, gaps: list, reversals: list, stamps: list,
           min_gap: int, source: str | None) -> None:
    print(f"📄 成品：{os.path.basename(md_path)}")
    print(f"   时间戳 {len(stamps)} 个"
          + (f"｜对照字幕：{os.path.basename(source)}" if source else "｜⚠️ 未找到 transcript.json，无法摘录被删内容"))
    print()

    if reversals:
        print(f"❌ 时间戳逆序 {len(reversals)} 处（硬伤，必须修）：")
        for r in reversals:
            print(f"   第 {r['index'] + 1} 个时间戳 [{fmt(r['cur'])}] 早于前一个 [{fmt(r['prev'])}]")
        print()
    else:
        print("✅ 时间戳全篇单调递增")
        print()

    if not gaps:
        print(f"✅ 没有 ≥{min_gap // 60} 分钟的删除区间")
        return

    hedged = sum(1 for g in gaps if g["hedge"])
    total = sum(g["seconds"] for g in gaps)
    print(f"⚠️  ≥{min_gap // 60} 分钟的删除区间 {len(gaps)} 处，合计 {total // 60} 分 {total % 60} 秒"
          + (f"，其中 {hedged} 处含让步/限定语" if hedged else ""))
    print("   逐条认领删除理由，且理由只能落在四类：广告口播 / 铺垫性长问 / 重复论证 / 纯附和回合。")
    print("   不属于这四类的一律补回；含让步语的尤其要看清楚——删掉会让立场比原话更硬。")
    print()
    for i, g in enumerate(gaps, 1):
        flag = " 🔺高风险（含让步/限定语）" if g["hedge"] else ""
        print(f"  {i}. [{fmt(g['start'])}–{fmt(g['end'])}] {g['seconds'] // 60}分{g['seconds'] % 60}秒"
              f"（{g['kind']}）{flag}")
        if g["excerpt"]:
            print(f"     原字幕：{g['excerpt']}")
        print("     删除理由：______（四类之一，否则补回）")
        print()


def main() -> int:
    args = sys.argv[1:]
    as_json = "--json" in args
    args = [a for a in args if a != "--json"]

    min_gap = DEFAULT_MIN_GAP
    if "--min-gap" in args:
        idx = args.index("--min-gap")
        if idx + 1 >= len(args):
            print("[ERROR] --min-gap 需要一个秒数", file=sys.stderr)
            return 1
        min_gap = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    transcript_path = None
    if "--transcript" in args:
        idx = args.index("--transcript")
        if idx + 1 >= len(args):
            print("[ERROR] --transcript 需要一个文件路径", file=sys.stderr)
            return 1
        transcript_path = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    if not args:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        print("Usage: check_transcript_edit.py <成品.md> [--transcript <transcript.json>] "
              "[--min-gap 120] [--json]", file=sys.stderr)
        return 1

    md_path = args[0]
    if not os.path.exists(md_path):
        print(f"[ERROR] 找不到成品文件：{md_path}", file=sys.stderr)
        return 1

    with open(md_path, encoding="utf-8") as f:
        md_text = f.read()
    stamps = parse_timestamps(md_text)

    rhythm = sentence_rhythm(md_text)
    if rhythm and not as_json:
        flag = "  ⚠️ 偏平，考虑长短句交替" if rhythm["cv"] < 0.40 else ""
        print(f"📐 句长节奏：{rhythm['sentences']} 句｜均值 {rhythm['mean']} 字｜"
              f"变异系数 {rhythm['cv']}{flag}")
        if rhythm["flat_runs"]:
            print(f"   连续三句长度相近 {rhythm['flat_runs']} 处（打断其中一句即可）")
        print()

    if not stamps:
        print("ℹ️  成品里没有时间戳（图文精读稿等形态不带时间戳），无需扫描。")
        return 0

    if transcript_path is None:
        transcript_path = locate_transcript(md_path)

    segments, duration = [], None
    if transcript_path and os.path.exists(transcript_path):
        with open(transcript_path, encoding="utf-8") as f:
            data = json.load(f)
        segments = parse_transcript(data.get("transcript", ""))
        duration = data.get("duration_seconds")
    else:
        transcript_path = None

    reversals = find_reversals(stamps)
    gaps = find_gaps(stamps, segments, duration, min_gap)

    if as_json:
        print(json.dumps({
            "file": md_path,
            "transcript": transcript_path,
            "timestamps": len(stamps),
            "reversals": reversals,
            "gaps": gaps,
            "min_gap_seconds": min_gap,
            "rhythm": rhythm,
        }, ensure_ascii=False, indent=2))
    else:
        report(md_path, gaps, reversals, stamps, min_gap, transcript_path)

    return 1 if reversals else 0


if __name__ == "__main__":
    sys.exit(main())
