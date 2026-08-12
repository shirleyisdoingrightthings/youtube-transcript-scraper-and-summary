#!/usr/bin/env python3
"""播客雷达（Podcast Radar）——监控 AI 行业播客频道，找出"相对自己频道基线异常火"的新片。

为什么不用 YouTube Data API：
  频道 RSS（https://www.youtube.com/feeds/videos.xml?channel_id=UC...）本身就带
  <media:statistics views="...">，最近 15 条上传全都有播放量。**零 API key、零配额、零成本。**
  只有"时长"RSS 里没有，需要时才去 watch 页抓一次 lengthSeconds（enrich 子命令）。

为什么不能按绝对播放量排序：
  大号随手一期就碾压小号的爆款，按播放量排永远只指向大号——而大号的内容中文圈早有人做。
  真正有信号的是**相对速度**：这一期相对该频道自己的基线有多反常。

    rel = 本片播放量 / 该频道成熟视频（≥21 天）的播放量中位数

  新片还没跑完生命周期，所以 rel 天然偏小；用一条经验成熟度曲线折算成 rel_adj 后
  才可跨"发布 1 天"与"发布 6 天"的片子比较。这条曲线是**拍脑袋的先验**，
  等 samples 表攒够两三周真实时间序列，就该换成按本项目自己的数据拟合（见 TODO）。

子命令：
  run                   一键：poll → enrich → report（手动触发的标准用法）
  resolve <handle>...   把 @handle 解析成 channel_id（配 radar_channels.json 用）
  poll                  抓一轮 RSS，写入 videos + samples
  enrich                给窗口内的片子补时长（抓 watch 页），用于剔除 Shorts / 估工作量
  report                出榜单（Markdown），默认最近 7 天

典型用法（按需手动跑，不常驻）：
  python3 radar.py run --days 7        # 过去一周
  python3 radar.py run --days 14       # 过去半个月

按需模式的两个已知代价（换来省心，可接受）：
  - RSS 只回每频道最近 15 条：隔两周才跑一次的话，高产频道（20VC / AI Engineer
    每天数更）更早的片子会漏。窗口开多宽，跑的间隔就别超过多宽的一半。
  - 单次采样只有播放量快照，没有增速；同一窗口内跑过两次以上，report 会自动
    用上真实增速。想要增速又不想花 token，可以只把 poll 挂 launchd（纯本地零 token）。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import http_utils

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "radar_channels.json")
DATA_DIR = os.path.join(BASE_DIR, "radar_data")
DB_PATH = os.path.join(DATA_DIR, "radar.db")
REPORT_DIR = os.path.join(DATA_DIR, "reports")

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
WATCH_URL = "https://www.youtube.com/watch?v={vid}"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# 成熟度先验：视频发布 d 天后，大致累计了生命周期播放量的百分之几。
# 仅用于把不同天龄的新片拉到同一把尺子上，不追求准确，只要单调且大致对。
# TODO: samples 表攒够 3 周后改为按本库真实数据拟合，删掉这张硬编码表。
MATURITY_CURVE = [
    (0.25, 0.12), (0.5, 0.20), (1, 0.32), (2, 0.44), (3, 0.53),
    (4, 0.59), (5, 0.64), (7, 0.72), (10, 0.79), (14, 0.85),
    (21, 0.93), (30, 1.00),
]

BASELINE_MIN_AGE_DAYS = 21     # 计入基线的"成熟视频"最小天龄
BASELINE_MIN_SAMPLES = 3       # 少于这么多条就认为基线不可信


# ---------------------------------------------------------------- 基础设施

def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def connect() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS channels (
            channel_id TEXT PRIMARY KEY,
            handle     TEXT,
            name       TEXT,
            weight     REAL DEFAULT 1.0
        );
        CREATE TABLE IF NOT EXISTS videos (
            video_id    TEXT PRIMARY KEY,
            channel_id  TEXT NOT NULL,
            title       TEXT,
            description TEXT,
            published   TEXT,        -- ISO8601 UTC
            duration_s  INTEGER,     -- enrich 后才有
            first_seen  TEXT
        );
        CREATE TABLE IF NOT EXISTS samples (
            video_id TEXT NOT NULL,
            ts       TEXT NOT NULL,  -- ISO8601 UTC，采样时刻
            views    INTEGER NOT NULL,
            PRIMARY KEY (video_id, ts)
        );
        CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
        CREATE INDEX IF NOT EXISTS idx_videos_pub     ON videos(published);
    """)
    return conn


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(s: str) -> datetime:
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def maturity(age_days: float) -> float:
    """按经验曲线线性插值，返回 (0,1] 的成熟度。"""
    if age_days >= MATURITY_CURVE[-1][0]:
        return 1.0
    prev_d, prev_m = MATURITY_CURVE[0]
    if age_days <= prev_d:
        return prev_m
    for d, m in MATURITY_CURVE[1:]:
        if age_days <= d:
            span = d - prev_d
            return prev_m + (m - prev_m) * ((age_days - prev_d) / span) if span else m
        prev_d, prev_m = d, m
    return 1.0


def human(n: int | None) -> str:
    if n is None:
        return "—"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def hhmm(seconds: int | None) -> str:
    if not seconds:
        return "—"
    return f"{seconds // 60}min"


# ---------------------------------------------------------------- resolve

def cmd_resolve(args) -> int:
    for handle in args.handles:
        h = handle.lstrip("@")
        resp = http_utils.get(f"https://www.youtube.com/@{h}",
                              headers={"User-Agent": UA}, timeout=25, label="resolve")
        m = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', resp.text)
        print(f"{h}\t{m.group(1) if m else 'FAIL'}")
    return 0


# ---------------------------------------------------------------- poll

def fetch_feed(ch: dict) -> tuple[dict, list[dict], str | None]:
    """抓一个频道的 RSS，返回 (频道, 条目列表, 错误信息)。"""
    try:
        resp = http_utils.get(FEED_URL.format(cid=ch["channel_id"]),
                              headers={"User-Agent": UA}, timeout=25,
                              label=f"rss:{ch['handle']}")
        if resp.status_code != 200:
            return ch, [], f"HTTP {resp.status_code}"
        root = ET.fromstring(resp.content)
    except Exception as e:  # noqa: BLE001 —— 单个频道挂了不该拖垮整轮
        return ch, [], f"{type(e).__name__}: {e}"

    entries = []
    for entry in root.findall("atom:entry", NS):
        vid = entry.findtext("yt:videoId", namespaces=NS)
        if not vid:
            continue
        group = entry.find("media:group", NS)
        desc = group.findtext("media:description", default="", namespaces=NS) if group is not None else ""
        stats = entry.find("media:group/media:community/media:statistics", NS)
        views = int(stats.get("views")) if stats is not None and stats.get("views") else None
        entries.append({
            "video_id": vid,
            "title": entry.findtext("atom:title", default="", namespaces=NS),
            "published": entry.findtext("atom:published", default="", namespaces=NS),
            "description": desc,
            "views": views,
        })
    return ch, entries, None


def cmd_poll(args) -> int:
    cfg = load_config()
    channels = cfg["channels"]
    conn = connect()
    ts = now_utc().isoformat()

    for ch in channels:
        conn.execute(
            "INSERT INTO channels(channel_id, handle, name, weight) VALUES(?,?,?,?) "
            "ON CONFLICT(channel_id) DO UPDATE SET handle=excluded.handle, "
            "name=excluded.name, weight=excluded.weight",
            (ch["channel_id"], ch["handle"], ch["name"], ch.get("weight", 1.0)))

    new_videos = 0
    failures = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        for ch, entries, err in pool.map(fetch_feed, channels):
            if err:
                failures.append(f"{ch['handle']}: {err}")
                continue
            for e in entries:
                cur = conn.execute("SELECT 1 FROM videos WHERE video_id=?", (e["video_id"],))
                if cur.fetchone() is None:
                    new_videos += 1
                conn.execute(
                    "INSERT INTO videos(video_id, channel_id, title, description, published, first_seen) "
                    "VALUES(?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET title=excluded.title",
                    (e["video_id"], ch["channel_id"], e["title"], e["description"], e["published"], ts))
                if e["views"] is not None:
                    conn.execute(
                        "INSERT OR REPLACE INTO samples(video_id, ts, views) VALUES(?,?,?)",
                        (e["video_id"], ts, e["views"]))
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0]
    print(f"✅ poll 完成 | 频道 {len(channels) - len(failures)}/{len(channels)} | "
          f"新片 {new_videos} | 库内累计 {total} 条")
    if failures:
        print(f"⚠️  {len(failures)} 个频道抓取失败：", file=sys.stderr)
        for f in failures:
            print(f"   - {f}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- enrich

def fetch_duration(vid: str) -> tuple[str, int | None, bool]:
    """抓 watch 页取 lengthSeconds。返回 (video_id, 时长, 是否疑似被限流)。

    watch 页约 1.4MB，且 YouTube 对高频抓取会直接返回几百字节的空壳页（不是 429，
    是 200 + 空内容），所以必须靠"响应体过小"来识别限流，并据此中止本轮。
    """
    try:
        resp = http_utils.get(WATCH_URL.format(vid=vid), headers={"User-Agent": UA},
                              timeout=25, label=f"dur:{vid}")
        if len(resp.content) < 50_000:
            return vid, None, True          # 空壳页 = 被限流
        m = re.search(r'"lengthSeconds":"(\d+)"', resp.text)
        return vid, (int(m.group(1)) if m else None), False
    except Exception:  # noqa: BLE001
        return vid, None, False


def cmd_enrich(args) -> int:
    """给窗口内的片子补时长。

    刻意做得很慢：串行 + 每条停 3~5 秒 + 单轮上限 80 条。这不是性能问题——watch 页
    没有配额概念，但抓猛了会被 YouTube 静默降级成空壳页（2026-08-11 实测：4 线程跑
    300 条即触发，且限流会**延续到次日**，让第二天的 RSS 间歇返回假 404，导致
    20 个频道里只有 7 个拿到当日采样）。时长写进 DB 后永不重抓，慢一次换长期干净的
    数据是划算的；补不完也没关系，下次 enrich 会接着补。
    """
    conn = connect()
    cutoff = (now_utc() - timedelta(days=args.days)).isoformat()
    rows = conn.execute(
        "SELECT video_id FROM videos WHERE published >= ? AND duration_s IS NULL "
        "ORDER BY published DESC", (cutoff,)).fetchall()
    ids = [r["video_id"] for r in rows][:args.limit] if args.limit else [r["video_id"] for r in rows]
    if not ids:
        print("✅ enrich 完成 | 窗口内无待补时长的片子")
        return 0

    ok = throttled = 0
    for i, vid in enumerate(ids, 1):
        vid, dur, blocked = fetch_duration(vid)
        if blocked:
            throttled += 1
            if throttled >= 3:
                conn.commit()
                print(f"⚠️  连续被限流，本轮提前收工 | 已补 {ok}/{len(ids)}，"
                      f"剩下的下次 enrich 会接着补", file=sys.stderr)
                return 0
            time.sleep(20)                   # 撞墙就退一步
            continue
        throttled = 0
        if dur:
            conn.execute("UPDATE videos SET duration_s=? WHERE video_id=?", (dur, vid))
            ok += 1
        if i % 10 == 0:
            conn.commit()                    # 增量落盘：中断不丢进度
            print(f"   … {i}/{len(ids)}", file=sys.stderr)
        time.sleep(random.uniform(*args.delay_range))
    conn.commit()
    print(f"✅ enrich 完成 | 补齐时长 {ok}/{len(ids)}")
    return 0


# ---------------------------------------------------------------- report

def latest_views(conn, video_id: str) -> tuple[int | None, str | None]:
    row = conn.execute(
        "SELECT views, ts FROM samples WHERE video_id=? ORDER BY ts DESC LIMIT 1",
        (video_id,)).fetchone()
    return (row["views"], row["ts"]) if row else (None, None)


def true_velocity(conn, video_id: str) -> float | None:
    """有 ≥2 次采样时，算最近两次之间的真实增速（次/天）。这才是最终该用的指标。"""
    rows = conn.execute(
        "SELECT views, ts FROM samples WHERE video_id=? ORDER BY ts DESC LIMIT 2",
        (video_id,)).fetchall()
    if len(rows) < 2:
        return None
    dt = (parse_iso(rows[0]["ts"]) - parse_iso(rows[1]["ts"])).total_seconds() / 86400
    if dt <= 0:
        return None
    return (rows[0]["views"] - rows[1]["views"]) / dt


def channel_baseline(conn, channel_id: str, now: datetime, min_duration_s: int,
                     exclude: str | None = None) -> tuple[float | None, int]:
    """该频道的基线播放量（"这个频道一期正常能跑多少"）。返回 (基线, 样本数)。

    首选成熟视频（≥21 天）的播放量中位数。但 RSS 只回最近 15 条，高产频道
    （每天发几条的）整页都不满 21 天，永远凑不出成熟样本——此时降级：
    对 ≥2 天的视频用成熟度曲线反推生命周期播放量（views / maturity(age)），
    取中位数。反推值噪音更大，但比"没有基线"强得多。
    `exclude` 用于把被打分的那条自己排除出基线，防止小样本频道自证热度。
    """
    rows = conn.execute(
        "SELECT video_id, published, duration_s FROM videos WHERE channel_id=?",
        (channel_id,)).fetchall()
    mature, est = [], []
    for r in rows:
        if not r["published"] or r["video_id"] == exclude:
            continue
        age = (now - parse_iso(r["published"])).total_seconds() / 86400
        # 时长未知的一律计入（多数是没被 enrich 的老片，剔掉会让样本更稀）
        if r["duration_s"] is not None and r["duration_s"] < min_duration_s:
            continue
        v, _ = latest_views(conn, r["video_id"])
        if not v:
            continue
        if age >= BASELINE_MIN_AGE_DAYS:
            mature.append(v)
        elif age >= 2:
            est.append(v / maturity(age))
    if len(mature) >= BASELINE_MIN_SAMPLES:
        return statistics.median(mature), len(mature)
    pool = mature + est
    if pool:
        return statistics.median(pool), len(pool)
    return None, 0


def match_guests(text: str, watchlist: list[str]) -> list[str]:
    low = text.lower()
    return [g for g in watchlist if g.lower() in low]


def cmd_report(args) -> int:
    cfg = load_config()
    watchlist = cfg.get("guest_watchlist", [])
    conn = connect()
    now = now_utc()
    cutoff = now - timedelta(days=args.days)
    min_dur = args.min_minutes * 60

    rows = conn.execute(
        "SELECT v.*, c.name AS channel_name, c.handle, c.weight "
        "FROM videos v JOIN channels c ON c.channel_id = v.channel_id "
        "WHERE v.published >= ? ORDER BY v.published DESC",
        (cutoff.isoformat(),)).fetchall()

    baselines: dict[str, tuple[float | None, int]] = {}
    items, skipped_short = [], 0

    for r in rows:
        dur = r["duration_s"]
        if dur is not None and dur < min_dur:
            skipped_short += 1
            continue
        views, _ = latest_views(conn, r["video_id"])
        if not views:
            continue
        age = max((now - parse_iso(r["published"])).total_seconds() / 86400, 0.05)

        base, base_n = channel_baseline(conn, r["channel_id"], now, min_dur,
                                        exclude=r["video_id"])
        baselines[r["channel_id"]] = (base, base_n)

        rel = views / base if base else None
        rel_adj = (rel / maturity(age)) if rel else None
        score = (rel_adj or 0) * (r["weight"] or 1.0)
        guests = match_guests(f"{r['title']} {r['description'][:600]}", watchlist)
        if guests:
            score *= 1.15

        items.append({
            "video_id": r["video_id"], "title": r["title"], "channel": r["channel_name"],
            "published": r["published"], "age": age, "views": views, "duration_s": dur,
            "baseline": base, "baseline_n": base_n, "rel_adj": rel_adj,
            "velocity": true_velocity(conn, r["video_id"]),
            "vpd": views / age, "guests": guests, "score": score,
        })

    items.sort(key=lambda x: x["score"], reverse=True)
    if args.top:
        items = items[:args.top]

    weak = [i["channel"] for i in items if i["baseline_n"] < BASELINE_MIN_SAMPLES]
    has_velocity = any(i["velocity"] is not None for i in items)

    lines = [
        f"# 播客雷达 · 最近 {args.days} 天",
        "",
        f"生成时间：{now.astimezone().strftime('%Y-%m-%d %H:%M %Z')} ｜ "
        f"监控频道 {len(baselines)} 个 ｜ 命中 {len(items)} 条"
        + (f"（已按时长 <{args.min_minutes}min 剔除 {skipped_short} 条）" if skipped_short else ""),
        "",
        "**热度 = 本片播放量 ÷ 该频道成熟视频播放量中位数，再按天龄折算成熟度。**"
        "跨频道可比，绝对播放量不可比。",
        "",
    ]
    if not has_velocity:
        lines += ["> ⚠️ 当前只有单次采样，热度用的是快照近似值。"
                  "连续 poll 两三周后会切到真实增速（Δ播放量/Δ时间），届时准确度会明显上一个台阶。", ""]
    if weak:
        lines += [f"> ⚠️ 这些频道的基线样本不足 {BASELINE_MIN_SAMPLES} 条，热度仅供参考："
                  + "、".join(sorted(set(weak))), ""]

    lines += ["| # | 热度 | 标题 | 频道 | 发布 | 播放 | 基线 | 时长 | 名单嘉宾 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for i, it in enumerate(items, 1):
        hot = f"{it['rel_adj']:.2f}x" if it["rel_adj"] else "—"
        lines.append(
            f"| {i} | **{hot}** | [{it['title'][:70]}](https://youtu.be/{it['video_id']}) "
            f"| {it['channel']} | {it['age']:.1f}d | {human(it['views'])} "
            f"| {human(int(it['baseline'])) if it['baseline'] else '—'} "
            f"| {hhmm(it['duration_s'])} | {'、'.join(it['guests']) or '—'} |")

    out = "\n".join(lines) + "\n"
    print(out)

    if args.md:
        os.makedirs(REPORT_DIR, exist_ok=True)
        path = args.md if os.path.isabs(args.md) else os.path.join(REPORT_DIR, args.md)
        with open(path, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"→ 已写入 {path}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------- run

def cmd_run(args) -> int:
    """一键跑全程：poll → enrich（只补窗口内，限量防限流）→ report。"""
    rc = cmd_poll(args)
    if rc:
        return rc
    # enrich 只补报告窗口内的片子；限量 + 礼貌停顿是为了别撞 YouTube 的静默限流
    en = argparse.Namespace(days=args.days + 1, limit=args.enrich_limit,
                            delay_range=(3.0, 5.0))
    cmd_enrich(en)
    rp = argparse.Namespace(days=args.days, min_minutes=args.min_minutes,
                            top=args.top, md=args.md)
    return cmd_report(rp)


# ---------------------------------------------------------------- main

def main() -> int:
    p = argparse.ArgumentParser(description="播客雷达：监控 AI 播客频道的相对热度")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("run", help="一键：poll → enrich → report")
    sp.add_argument("--days", type=int, default=7, help="报告窗口（天），如 7 / 14")
    sp.add_argument("--min-minutes", type=int, default=20)
    sp.add_argument("--top", type=int, default=0)
    sp.add_argument("--md", help="同时写入 radar_data/reports/ 下的该文件名")
    sp.add_argument("--enrich-limit", type=int, default=80,
                    help="本轮最多补几条时长（防限流），0 为不限。80 是实测安全上限，"
                         "调高会显著提升被 YouTube 静默限流的概率")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("resolve", help="把 @handle 解析成 channel_id")
    sp.add_argument("handles", nargs="+")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("poll", help="抓一轮 RSS 并采样播放量")
    sp.set_defaults(func=cmd_poll)

    sp = sub.add_parser("enrich", help="给窗口内的片子补时长")
    sp.add_argument("--days", type=int, default=14)
    sp.add_argument("--limit", type=int, default=80,
                    help="本轮最多补几条，0 为不限（不建议：一轮抓太多会触发软限流）")
    sp.add_argument("--delay-range", type=float, nargs=2, default=(3.0, 5.0),
                    metavar=("MIN", "MAX"), help="每条之间的随机停顿秒数，别调到 3 秒以下")
    sp.set_defaults(func=cmd_enrich)

    sp = sub.add_parser("report", help="出榜单")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--min-minutes", type=int, default=20, help="低于此时长视为短视频，剔除")
    sp.add_argument("--top", type=int, default=0, help="只留前 N 条，0 为不限")
    sp.add_argument("--md", help="同时写入 radar_data/reports/ 下的该文件名")
    sp.set_defaults(func=cmd_report)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
