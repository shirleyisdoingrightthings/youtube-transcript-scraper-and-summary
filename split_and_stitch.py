#!/usr/bin/env python3
"""长视频（>45 分钟）分段并行编译与断点续传工具：切分字幕 (split) + 校验拼接归档 (stitch)。

Usage:
    # 1. 将长字幕按章节/时长切分为 N 段（默认 3 段），写入 output/_work_<video_id>/
    python3 split_and_stitch.py split <transcript.json> [--parts 3] [--work-dir <dir>]

    # 2. 将已编译的各段带时间戳稿与导读壳拼接、跑 check_transcript_edit.py 机检、剥离时间戳并归档至 output/<标题>/
    python3 split_and_stitch.py stitch --work-dir <dir> --front-matter <front_matter.md> \
        --title "<中文标题>" [--transcript <transcript.json>] [--endnote "<⚠️说明>"] [--clean-work]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

TIMESTAMP_LINE_RE = re.compile(r"^\[(\d{1,3}):([0-5]\d)\]\s*(.*)$")
DESC_CHAPTER_RE = re.compile(r"(?m)^(\d{1,2}):(\d{2})(?::(\d{2}))?\s*[–—-]\s*(.+)$")
AD_CUE_RE = re.compile(
    r"\b(?:my\s+sponsor|brought\s+to\s+you\s+by|use\s+code|50%\s+off\s+your\s+first\s+month)\b",
    re.IGNORECASE,
)

TS_LINE_ONLY = re.compile(r"(?m)^[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*\n")
TS_LINE_START = re.compile(r"(?m)^[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*")
TS_INLINE_ASCII = re.compile(
    r"([A-Za-z0-9])[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*([A-Za-z0-9])"
)
TS_INLINE_ANY = re.compile(r"[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*")


def fmt_mmss(sec: int) -> str:
    return f"{sec // 60:02d}:{sec % 60:02d}"


def strip_timestamps(text: str) -> str:
    """确定性剥离 [MM:SS] 时间戳并规范化行内空白。"""
    s = text.replace("\r\n", "\n")
    s = TS_LINE_ONLY.sub("", s)
    s = TS_LINE_START.sub("", s)
    s = TS_INLINE_ASCII.sub(r"\1 \2", s)
    s = TS_INLINE_ANY.sub("", s)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    return "\n".join(lines).strip() + "\n"


def parse_description_chapters(description: str | None) -> list[dict]:
    if not description:
        return []
    chapters = []
    for m in DESC_CHAPTER_RE.finditer(description):
        if m.group(3) is not None:
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        else:
            sec = int(m.group(1)) * 60 + int(m.group(2))
        chapters.append({
            "seconds": sec,
            "mmss": fmt_mmss(sec),
            "title": m.group(4).strip(),
        })
    return chapters


def cmd_split(args: argparse.Namespace) -> int:
    tpath = Path(args.transcript).resolve()
    if not tpath.is_file():
        print(f"[ERROR] 找不到字幕文件：{tpath}", file=sys.stderr)
        return 1

    data = json.loads(tpath.read_text(encoding="utf-8"))
    video_id = data.get("video_id") or "unknown"
    raw_lines = data.get("transcript", "").splitlines()
    if not raw_lines:
        print("[ERROR] 字幕内容为空", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parent
    work_dir = (
        Path(args.work_dir).resolve()
        if args.work_dir
        else (repo_root / "output" / f"_work_{video_id}")
    )
    work_dir.mkdir(parents=True, exist_ok=True)

    chapters = parse_description_chapters(data.get("description"))
    n_parts = max(1, int(args.parts))
    total_lines = len(raw_lines)

    line_secs = []
    ad_candidate_lines = []
    for idx, ln in enumerate(raw_lines):
        m = TIMESTAMP_LINE_RE.match(ln.strip())
        sec = int(m.group(1)) * 60 + int(m.group(2)) if m else (line_secs[-1] if line_secs else 0)
        line_secs.append(sec)
        if AD_CUE_RE.search(ln):
            ad_candidate_lines.append({"line_1based": idx + 1, "mmss": fmt_mmss(sec), "text": ln[:100]})

    boundaries = [0]
    if len(chapters) >= n_parts and n_parts > 1:
        for k in range(1, n_parts):
            ch_idx = round(k * len(chapters) / n_parts)
            target_sec = chapters[min(ch_idx, len(chapters) - 1)]["seconds"]
            split_line = next(
                (i for i, s in enumerate(line_secs) if s >= max(0, target_sec - 5)),
                round(k * total_lines / n_parts),
            )
            boundaries.append(split_line)
    else:
        for k in range(1, n_parts):
            boundaries.append(round(k * total_lines / n_parts))
    boundaries.append(total_lines)

    parts_meta = []
    for p_idx in range(n_parts):
        start_0 = boundaries[p_idx]
        end_0 = boundaries[p_idx + 1]
        slice_lines = raw_lines[start_0:end_0]
        raw_file = work_dir / f"part{p_idx + 1}_raw.txt"
        out_md = work_dir / f"part{p_idx + 1}_timestamped.md"
        raw_file.write_text("\n".join(slice_lines) + "\n", encoding="utf-8")

        part_chapters = [
            c for c in chapters
            if line_secs[start_0] - 10 <= c["seconds"] <= (line_secs[end_0 - 1] + 10 if end_0 > start_0 else 0)
        ]
        status = "completed" if out_md.is_file() and out_md.stat().st_size > 100 else "pending"
        parts_meta.append({
            "part": p_idx + 1,
            "line_start_1based": start_0 + 1,
            "line_end_1based": end_0,
            "time_start": fmt_mmss(line_secs[start_0]) if end_0 > start_0 else "00:00",
            "time_end": fmt_mmss(line_secs[end_0 - 1]) if end_0 > start_0 else "00:00",
            "raw_file": str(raw_file),
            "target_md": str(out_md),
            "chapters": part_chapters,
            "status": status,
        })

    manifest = {
        "video_id": video_id,
        "title": data.get("title"),
        "duration_seconds": data.get("duration_seconds"),
        "source_transcript": str(tpath),
        "work_dir": str(work_dir),
        "parts_count": n_parts,
        "ad_candidate_lines": ad_candidate_lines,
        "parts": parts_meta,
    }
    manifest_path = work_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"✅ 已切分 {n_parts} 段至工作目录：{work_dir}")
    for pm in parts_meta:
        tag = "✅ [已存在·可跳过]" if pm["status"] == "completed" else "⏳ [待编译]"
        print(
            f"  Part {pm['part']} {tag}: L{pm['line_start_1based']}–L{pm['line_end_1based']} "
            f"([{pm['time_start']}]–[{pm['time_end']}]) -> {os.path.basename(pm['target_md'])}"
        )
    return 0


def cmd_stitch(args: argparse.Namespace) -> int:
    work_dir = Path(args.work_dir).resolve()
    manifest_path = work_dir / "manifest.json"
    if not manifest_path.is_file():
        print(f"[ERROR] 找不到 manifest.json：{manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tpath = Path(args.transcript).resolve() if args.transcript else Path(manifest["source_transcript"])
    if not tpath.is_file():
        print(f"[ERROR] 找不到原始字幕 JSON：{tpath}", file=sys.stderr)
        return 1

    fm_path = Path(args.front_matter).resolve()
    if not fm_path.is_file():
        print(f"[ERROR] 找不到导读壳文件：{fm_path}", file=sys.stderr)
        return 1

    fm_text = fm_path.read_text(encoding="utf-8").strip()
    part_texts = []
    for pm in manifest["parts"]:
        pmd = Path(pm["target_md"])
        if not pmd.is_file():
            print(f"[ERROR] 分段文件尚未生成：{pmd}", file=sys.stderr)
            return 1
        part_texts.append(pmd.read_text(encoding="utf-8").strip())

    full_working = fm_text + "\n\n\n" + "\n\n\n".join(part_texts)
    if args.endnote:
        full_working += "\n\n" + args.endnote.strip()
    full_working += "\n"

    working_draft_path = work_dir / "working_draft_with_timestamps.md"
    working_draft_path.write_text(full_working, encoding="utf-8")

    repo_root = Path(__file__).resolve().parent
    edit_script = repo_root / "check_transcript_edit.py"
    proc = subprocess.run(
        [sys.executable, "-B", str(edit_script), str(working_draft_path), "--transcript", str(tpath)],
        capture_output=True,
        text=True,
        check=False,
    )
    print(proc.stdout, end="")
    if proc.returncode != 0:
        print(proc.stderr, file=sys.stderr)
        print("❌ 时间轴机检未通过（存在时间戳逆序），已中止去时间戳与归档。", file=sys.stderr)
        return 1

    clean_title = re.sub(r'[/\\:*?"<>|]', "-", args.title).strip(" .")
    if not clean_title:
        print("[ERROR] 标题清洗后为空，请提供有效中文标题", file=sys.stderr)
        return 1
    output_root = (repo_root / "output").resolve()
    final_dir = (output_root / clean_title).resolve()
    if final_dir.parent != output_root:
        print("[ERROR] 标题包含非法路径跳转字符，已拒绝写入", file=sys.stderr)
        return 1
    final_dir.mkdir(parents=True, exist_ok=True)
    final_md_path = final_dir / f"{clean_title} - 逐字稿.md"
    final_json_path = final_dir / "transcript.json"

    final_md_path.write_text(strip_timestamps(full_working), encoding="utf-8")
    shutil.copyfile(tpath, final_json_path)
    print(f"✅ Step 3 完成 | 已归档（成品 + transcript.json）至：output/{clean_title}/")

    if args.clean_work and work_dir.exists() and work_dir != final_dir:
        shutil.rmtree(work_dir)
        print(f"🧹 已清理临时分段目录：{work_dir.name}")

    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="长视频分段并行编译与断点续传工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("split", help="将长字幕切分为 N 段并写入工作目录")
    sp.add_argument("transcript", help="原始字幕 JSON 路径（如 transcript_temp.json）")
    sp.add_argument("--parts", type=int, default=3, help="切分段数（默认 3）")
    sp.add_argument("--work-dir", default=None, help="自定义分段工作目录（默认 output/_work_<video_id>）")

    st = sub.add_parser("stitch", help="拼接分段稿与导读壳、执行机检、去时间戳并归档")
    st.add_argument("--work-dir", required=True, help="分段工作目录路径")
    st.add_argument("--front-matter", required=True, help="导读壳 Markdown 路径（标题/题记/署名/编者按/核心看点/嘉宾背景）")
    st.add_argument("--title", required=True, help="生成的中文标题")
    st.add_argument("--transcript", default=None, help="原始字幕 JSON 路径（默认从 manifest.json 读取）")
    st.add_argument("--endnote", default=None, help="可选文末 ⚠️ 说明行")
    st.add_argument("--clean-work", action="store_true", help="归档成功后自动清理临时分段目录")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "split":
        return cmd_split(args)
    if args.cmd == "stitch":
        return cmd_stitch(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
