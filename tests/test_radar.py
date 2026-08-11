#!/usr/bin/env python3
"""播客雷达的回归测试。

守的是这类失败模式：基线算错不会报错，只会**静默扭曲整个排名**——
比如把被打分的视频算进它自己的基线（小样本频道自证热度）、
高产频道凑不出成熟样本时降级路径失效（整个频道从榜单消失）、
RSS 里的播放量没解析出来（热度全变 "—"）。这些光看终端输出都发现不了。
"""
import os
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from _bootstrap import check, ok

import radar


# ---------------------------------------------------------------- 工具

def _mem_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE channels (channel_id TEXT PRIMARY KEY, handle TEXT, name TEXT, weight REAL);
        CREATE TABLE videos (video_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT,
                             description TEXT, published TEXT, duration_s INTEGER, first_seen TEXT);
        CREATE TABLE samples (video_id TEXT, ts TEXT, views INTEGER, PRIMARY KEY (video_id, ts));
    """)
    return conn


def _add_video(conn, vid, channel, age_days, views, duration_s=3600, now=None):
    now = now or datetime.now(timezone.utc)
    pub = (now - timedelta(days=age_days)).isoformat()
    conn.execute("INSERT INTO videos(video_id, channel_id, published, duration_s, title, description) "
                 "VALUES(?,?,?,?,?,?)", (vid, channel, pub, duration_s, vid, ""))
    conn.execute("INSERT INTO samples(video_id, ts, views) VALUES(?,?,?)",
                 (vid, now.isoformat(), views))


# ---------------------------------------------------------------- 测试

def test_maturity_monotonic():
    """成熟度曲线必须单调不减且收敛到 1——否则天龄折算会把新片排乱。"""
    prev = 0.0
    for d in [0.1, 0.5, 1, 2, 3, 5, 7, 10, 14, 21, 30, 60]:
        m = radar.maturity(d)
        check(prev <= m <= 1.0, f"maturity({d}d) = {m:.2f}，单调且 ≤1") if d == 60 else None
        assert prev <= m <= 1.0, f"maturity 在 {d}d 处不单调：{prev} -> {m}"
        prev = m
    check(abs(radar.maturity(30) - 1.0) < 1e-9, "maturity(30d) 收敛到 1.0")
    ok("成熟度曲线全程单调不减")


def test_baseline_mature_path():
    """有 ≥3 条成熟视频（≥21 天）时，基线 = 它们的中位数，正常路径。"""
    conn = _mem_conn()
    for i, v in enumerate([10_000, 20_000, 30_000]):
        _add_video(conn, f"old{i}", "ch1", age_days=30 + i, views=v)
    now = datetime.now(timezone.utc)
    base, n = radar.channel_baseline(conn, "ch1", now, min_duration_s=1200)
    check(base == 20_000 and n == 3, "成熟路径：基线 = 三条成熟视频的中位数", (base, n))


def test_baseline_fallback_for_prolific_channel():
    """高产频道 RSS 全是新片、没有一条 ≥21 天——降级路径必须给出反推基线，
    否则这类频道会因"无基线"从热度榜整个消失（正是 8/11 首跑撞上的问题）。"""
    conn = _mem_conn()
    now = datetime.now(timezone.utc)
    # 4 条 3~6 天的新片，各 1 万播放；maturity(3d)≈0.53 → 反推生命周期 ≈ 1.9 万
    for i in range(4):
        _add_video(conn, f"new{i}", "ch2", age_days=3 + i, views=10_000, now=now)
    base, n = radar.channel_baseline(conn, "ch2", now, min_duration_s=1200)
    check(base is not None and n == 4, "降级路径：无成熟样本时用反推值兜底", (base, n))
    check(base and base > 10_000, "反推基线 > 当前播放量（补足了未走完的生命周期）", base)


def test_baseline_excludes_scored_video():
    """被打分的那条必须排除出自己频道的基线——不排除的话，小样本频道的
    爆款会拉高自家基线、把自己的热度压回去，雷达对黑马频道就失灵了。"""
    conn = _mem_conn()
    now = datetime.now(timezone.utc)
    _add_video(conn, "hit", "ch3", age_days=3, views=100_000, now=now)   # 爆款
    for i in range(3):
        _add_video(conn, f"norm{i}", "ch3", age_days=4 + i, views=1_000, now=now)
    with_excl, _ = radar.channel_baseline(conn, "ch3", now, 1200, exclude="hit")
    without_excl, _ = radar.channel_baseline(conn, "ch3", now, 1200)
    check(with_excl < without_excl, "排除被打分视频后基线更低（爆款没有污染自家基线）",
          (with_excl, without_excl))


def test_rss_parse_views_and_fields():
    """RSS 解析必须拿到 videoId / title / published / views——views 丢了
    热度全变 '—'，榜单退化成时间线，不报任何错。"""
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Test Channel</title>
 <entry>
  <id>yt:video:abc12345678</id>
  <yt:videoId>abc12345678</yt:videoId>
  <title>Test Episode One</title>
  <published>2026-08-05T10:00:00+00:00</published>
  <media:group>
   <media:title>Test Episode One</media:title>
   <media:description>A guest talks about things.</media:description>
   <media:community>
    <media:statistics views="123456"/>
   </media:community>
  </media:group>
 </entry>
</feed>"""
    root = ET.fromstring(xml)
    entries = []
    for entry in root.findall("atom:entry", radar.NS):
        vid = entry.findtext("yt:videoId", namespaces=radar.NS)
        stats = entry.find("media:group/media:community/media:statistics", radar.NS)
        views = int(stats.get("views")) if stats is not None and stats.get("views") else None
        entries.append((vid, entry.findtext("atom:title", namespaces=radar.NS),
                        entry.findtext("atom:published", namespaces=radar.NS), views))
    check(len(entries) == 1, "RSS fixture 解析出 1 条")
    vid, title, pub, views = entries[0]
    check(vid == "abc12345678" and views == 123456, "videoId 与播放量解析正确", (vid, views))
    check(title == "Test Episode One" and pub.startswith("2026-08-05"), "标题与发布时间解析正确")


def test_true_velocity_needs_two_samples():
    """真实增速：单次采样必须返回 None（report 才知道降级用快照），
    两次采样必须算出 Δviews/Δt。"""
    conn = _mem_conn()
    now = datetime.now(timezone.utc)
    _add_video(conn, "v1", "ch4", age_days=2, views=1_000, now=now - timedelta(days=1))
    check(radar.true_velocity(conn, "v1") is None, "单次采样 → 增速为 None（不硬编）")
    conn.execute("INSERT INTO samples(video_id, ts, views) VALUES(?,?,?)",
                 ("v1", now.isoformat(), 3_000))
    vel = radar.true_velocity(conn, "v1")
    check(vel is not None and abs(vel - 2_000) < 1, "两次采样 → 增速 = Δviews/Δ天", vel)


def main():
    print("test_radar：")
    test_maturity_monotonic()
    test_baseline_mature_path()
    test_baseline_fallback_for_prolific_channel()
    test_baseline_excludes_scored_video()
    test_rss_parse_views_and_fields()
    test_true_velocity_needs_two_samples()


if __name__ == "__main__":
    main()
