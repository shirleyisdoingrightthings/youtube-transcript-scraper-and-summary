"""精编稿体检（时间戳逆序 + 时间轴缺口扫描）的回归测试。

守的是这个失败模式：精编初稿静默删掉整段关键问答，成品读起来依然连贯，
初稿自检看不出来——必须靠算的，不能靠模型自觉。
"""
import json
import os
import tempfile

from _bootstrap import check

import check_transcript_edit as ce


def _fixture():
    """造一份 47 分钟的原字幕 + 一份删了三段的精编稿。"""
    lines = []
    for m in range(0, 48):
        text = "we kept building and shipping things"
        if m == 30:                       # 被删区间里埋一句让步语
            text = "Of course, that is not always true, there are exceptions."
        lines.append(f"[{m:02d}:00] {text}")
    transcript = {"transcript": "\n".join(lines), "duration_seconds": 2860}

    kept = [0, 1, 2, 3, 4, 20, 21, 22, 29, 33, 34]     # 缺口：04–20、22–29、29–33
    md = "\n\n".join(f"**[{m:02d}:00] 嘉宾：** 内容 {m}" for m in kept)

    folder = tempfile.mkdtemp()
    md_path = os.path.join(folder, "某某｜某主题 - 逐字稿.md")
    tx_path = os.path.join(folder, "transcript.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(tx_path, "w", encoding="utf-8") as f:
        json.dump(transcript, f, ensure_ascii=False)
    return md_path, tx_path


def test_gap_scan():
    md_path, _ = _fixture()
    with open(md_path, encoding="utf-8") as f:
        stamps = ce.parse_timestamps(f.read())
    with open(ce.locate_transcript(md_path), encoding="utf-8") as f:
        data = json.load(f)
    segments = ce.parse_transcript(data["transcript"])

    check(ce.locate_transcript(md_path).endswith("transcript.json"),
          "同目录自动找到 transcript.json（归档三件套就在一起）")

    gaps = ce.find_gaps(stamps, segments, data["duration_seconds"], 120)
    ranges = [(ce.fmt(g["start"]), ce.fmt(g["end"]), g["kind"]) for g in gaps]
    check(ranges == [("04:00", "20:00", "中段"), ("22:00", "29:00", "中段"),
                     ("29:00", "33:00", "中段"), ("34:00", "47:40", "片尾")],
          "扫出全部 ≥2 分钟的删除区间，含片尾", ranges)

    check(all(g["excerpt"] for g in gaps[:3]),
          "每个区间都摘出原字幕，便于逐条认领删除理由")

    hedged = [(ce.fmt(g["start"]), ce.fmt(g["end"])) for g in gaps if g["hedge"]]
    check(hedged == [("29:00", "33:00")],
          "含让步/限定语的区间被标为高风险（删掉会让立场比原话更硬）", hedged)

    check(ce.find_gaps(stamps, segments, data["duration_seconds"], 600)[0]["seconds"] >= 600,
          "--min-gap 可调，只看更大的缺口")


def test_no_gap_and_reversal():
    full = "\n\n".join(f"**[{m:02d}:00] 嘉宾：** 内容" for m in range(0, 20))
    stamps = ce.parse_timestamps(full)
    check(ce.find_gaps(stamps, [], 1200, 120) == [],
          "完整存档版（未删减）扫不出缺口")
    check(ce.find_reversals(stamps) == [], "顺序正常时无逆序告警")

    bad = ce.parse_timestamps("**[10:00]** 甲\n\n**[09:30]** 乙\n\n**[11:00]** 丙")
    rev = ce.find_reversals(bad)
    check(len(rev) == 1 and rev[0]["prev"] == 600 and rev[0]["cur"] == 570,
          "时间倒流被抓出来（硬伤）", rev)

    check(ce.parse_timestamps("**[70:06]** 甲")[0][0] == 4206,
          "分钟数超过 59 也能解析（长播客的 [70:06]）")


def test_exit_codes():
    md_path, tx_path = _fixture()
    import subprocess
    import sys as _sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    r = subprocess.run([_sys.executable, os.path.join(root, "check_transcript_edit.py"),
                        md_path, "--json"], capture_output=True, text=True)
    payload = json.loads(r.stdout)
    check(r.returncode == 0 and len(payload["gaps"]) == 4 and payload["reversals"] == [],
          "只有缺口没有逆序 → exit 0，缺口清单照常输出（缺口要人来认领，不是失败）",
          r.returncode)

    with open(md_path, "a", encoding="utf-8") as f:
        f.write("\n\n**[05:00] 嘉宾：** 时间倒流了")
    r = subprocess.run([_sys.executable, os.path.join(root, "check_transcript_edit.py"),
                        md_path], capture_output=True, text=True)
    check(r.returncode == 1 and "时间戳逆序" in r.stdout,
          "出现逆序 → exit 1（硬伤，必须修）", r.returncode)

    empty = os.path.join(tempfile.mkdtemp(), "图文精读.md")
    with open(empty, "w", encoding="utf-8") as f:
        f.write("# 标题\n\n正文没有时间戳。")
    r = subprocess.run([_sys.executable, os.path.join(root, "check_transcript_edit.py"),
                        empty], capture_output=True, text=True)
    check(r.returncode == 0 and "没有时间戳" in r.stdout,
          "图文精读稿等无时间戳形态 → 直接放行，不报错", r.returncode)


def main():
    print("── 精编稿体检（逆序 + 缺口扫描）──")
    test_gap_scan()
    test_no_gap_and_reversal()
    test_exit_codes()


if __name__ == "__main__":
    main()
