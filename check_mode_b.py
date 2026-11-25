#!/usr/bin/env python3
"""模式 B（对话体逐字稿）全量静态体检器：共有壳结构、空行状态机、说话人标签、加粗、数字体例、零 AI 味、术语表、⚠️ 对等性与工作稿等价核验。

Usage:
    python3 check_mode_b.py <成品.md> [--working-draft <带时间戳工作稿.md>]
                            [--transcript <transcript.json>] [--pure-text] [--json]
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

Status = Literal["PASS", "WARN", "FAIL"]

BYLINE_1_PREFIX = "👩 编译"
BYLINE_2_PREFIX = "🧑‍🎨 排版"
SENTENCE_END_RE = re.compile(r"[。！？]+")

TS_LINE_ONLY = re.compile(r"(?m)^[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*\n")
TS_LINE_START = re.compile(r"(?m)^[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*")
TS_INLINE_ASCII = re.compile(
    r"([A-Za-z0-9])[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*([A-Za-z0-9])"
)
TS_INLINE_ANY = re.compile(r"[ \t]*\[\d{1,3}:[0-5]\d\][ \t]*")

TIMESTAMP_BRACKET_RE = re.compile(r"\[\d{1,3}:[0-5]\d(?::[0-5]\d)?\]")
STAGE_DIR_RE = re.compile(
    r"\[(?:笑|大笑|笑声|掌声|鼓掌|叹气|沉默|停顿|laughter|applause)\]",
    re.IGNORECASE,
)
UNCOMMAD_INT_RE = re.compile(r"(?<![\d.,A-Za-z_/-])([1-9]\d{3,})(?![\d.,A-Za-z_])")
BAD_RANGE_DASH_RE = re.compile(r"\d+(?:\.\d+)?%?\s*(?:——|—|–|~|～)\s*\d+(?:\.\d+)?%?")
PERCENT_CJK_RE = re.compile(r"百分之[一二三四五六七八九十百千万点零两]+")

TIER1_BANNED_19 = [
    "值得一提的是", "不难看出", "综上所述", "换句话说", "某种程度上",
    "令人瞩目", "难得地", "赋能", "助力", "打造", "抓手", "闭环",
    "颗粒度", "深远影响", "前所未有", "拭目以待", "保姆级", "其它", "堆栈",
]

BANNED_GLOSSARY = [
    ("智能体", "请统一用 'Agent'"),
    ("提示词", "请统一用 'Prompt'"),
    ("嵌入表征", "请区分 '嵌入向量' 与 '表征'"),
    ("流动率", "retention 请译为 '留存率'"),
]

BUSHI_ERSHI_RE = re.compile(r"(?<!是)不是[^。！？\n]{1,60}?而是")


@dataclass
class CheckResult:
    check_id: str
    name: str
    status: Status
    message: str
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }


@dataclass
class Block:
    kind: str
    lines: list[str]
    start_line: int
    end_line: int
    blank_before: int

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class Chapter:
    title: str
    heading_line: int
    blocks: list[Block]

    @property
    def body_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


def strip_timestamps_for_diff(text: str) -> list[str]:
    s = text.replace("\r\n", "\n")
    s = TS_LINE_ONLY.sub("", s)
    s = TS_LINE_START.sub("", s)
    s = TS_INLINE_ASCII.sub(r"\1 \2", s)
    s = TS_INLINE_ANY.sub("", s)
    return [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines()]


def normalize_lines_for_diff(text: str) -> list[str]:
    s = text.replace("\r\n", "\n")
    return [re.sub(r"[ \t]+", " ", line).strip() for line in s.splitlines()]


def is_speaker_tag(line: str) -> bool:
    s = line.strip()
    return bool(re.match(r"^(?:🎙️|👱‍♂️|👩|👤)\s+\S+", s))


def parse_document(raw_text: str) -> dict:
    norm = raw_text.replace("\r\n", "\n")
    has_trailing_newline = norm.endswith("\n")
    stripped_one = norm[:-1] if has_trailing_newline else norm
    raw_lines = stripped_one.split("\n") if stripped_one != "" else []

    eof_blank_lines = 0
    idx = len(raw_lines) - 1
    while idx >= 0 and raw_lines[idx].strip() == "":
        eof_blank_lines += 1
        idx -= 1

    max_blanks = 0
    cur_blanks = 0
    for ln in raw_lines:
        if ln.strip() == "":
            cur_blanks += 1
            max_blanks = max(max_blanks, cur_blanks)
        else:
            cur_blanks = 0

    blocks: list[Block] = []
    in_key_points = False
    seen_top_h1 = False
    seen_guest_bio = False
    in_body_chapters = False

    n = len(raw_lines)
    i = 0
    pending_blanks = 0
    while i < n:
        line = raw_lines[i]
        if line.strip() == "":
            pending_blanks += 1
            i += 1
            continue
        stripped = line.strip()
        if re.match(r"^#{1,6}(?:\s|$)", line):
            if not seen_top_h1 and line.startswith("# "):
                kind = "TOP_H1"
                seen_top_h1 = True
            else:
                kind = "OTHER_H1"
                if stripped == "# 核心看点":
                    in_key_points = True
                elif stripped == "# 嘉宾背景":
                    in_key_points = False
                    seen_guest_bio = True
                elif seen_guest_bio and line.startswith("# "):
                    in_key_points = False
                    in_body_chapters = True
            blocks.append(Block(kind, [line], i + 1, i + 1, pending_blanks))
            pending_blanks = 0
            i += 1
            continue
        if stripped.startswith(BYLINE_1_PREFIX):
            blocks.append(Block("BYLINE_1", [line], i + 1, i + 1, pending_blanks))
            pending_blanks = 0
            i += 1
            continue
        if stripped.startswith(BYLINE_2_PREFIX):
            blocks.append(Block("BYLINE_2", [line], i + 1, i + 1, pending_blanks))
            pending_blanks = 0
            i += 1
            continue
        if is_speaker_tag(line):
            blocks.append(Block("SPEAKER_TAG", [line], i + 1, i + 1, pending_blanks))
            pending_blanks = 0
            i += 1
            continue
        if in_key_points and re.match(r"^[-*+]\s+", line):
            start = i
            item_lines = [line]
            i += 1
            while i < n and raw_lines[i].strip() != "" and not re.match(r"^[-*+#]", raw_lines[i]):
                item_lines.append(raw_lines[i])
                i += 1
            blocks.append(Block("BULLET", item_lines, start + 1, i, pending_blanks))
            pending_blanks = 0
            continue
        if line.lstrip().startswith(">"):
            start = i
            q_lines = [line]
            i += 1
            while i < n and raw_lines[i].strip() != "" and raw_lines[i].lstrip().startswith(">"):
                q_lines.append(raw_lines[i])
                i += 1
            kind = "BIO_CALLOUT" if (seen_guest_bio and not in_body_chapters) else ("EPIGRAPH" if not in_body_chapters else "SPEECH_PARA")
            blocks.append(Block(kind, q_lines, start + 1, i, pending_blanks))
            pending_blanks = 0
            continue

        start = i
        p_lines = [line]
        i += 1
        while i < n and raw_lines[i].strip() != "":
            nxt = raw_lines[i]
            nxt_s = nxt.strip()
            if (
                re.match(r"^#{1,6}(?:\s|$)", nxt)
                or nxt_s.startswith((BYLINE_1_PREFIX, BYLINE_2_PREFIX))
                or is_speaker_tag(nxt)
            ):
                break
            p_lines.append(nxt)
            i += 1
        kind = "SPEECH_PARA" if in_body_chapters else "FRONT_PARA"
        blocks.append(Block(kind, p_lines, start + 1, i, pending_blanks))
        pending_blanks = 0

    endnote_blocks: list[Block] = []
    if blocks:
        tail_idx = len(blocks)
        while tail_idx > 0:
            blk = blocks[tail_idx - 1]
            if blk.kind == "SPEECH_PARA" and all(re.match(r"^(?:-\s*)?⚠️", ln.strip()) for ln in blk.lines):
                tail_idx -= 1
            else:
                break
        if tail_idx < len(blocks):
            endnote_blocks = blocks[tail_idx:]
            blocks = blocks[:tail_idx]

    chapters: list[Chapter] = []
    epigraphs: list[Block] = []
    editor_notes: list[Block] = []
    key_points: list[Block] = []
    guest_bios: list[Block] = []
    section = "PRE_KP"
    cur_ch: Chapter | None = None
    top_title = None

    for blk in blocks:
        if blk.kind == "TOP_H1":
            top_title = blk.lines[0][2:].strip()
            continue
        if blk.kind == "OTHER_H1":
            h_text = re.sub(r"^#+\s*", "", blk.lines[0]).strip()
            if h_text == "核心看点" and cur_ch is None:
                section = "KP"
                continue
            if h_text == "嘉宾背景" and cur_ch is None:
                section = "BIO"
                continue
            section = "CH"
            cur_ch = Chapter(h_text, blk.start_line, [])
            chapters.append(cur_ch)
            continue
        if section == "PRE_KP":
            if blk.kind == "EPIGRAPH":
                epigraphs.append(blk)
            elif blk.kind == "FRONT_PARA":
                if not re.match(r"^(?:🖼️|!\[)", blk.text.strip()):
                    blk.kind = "EDITOR_NOTE_PARA"
                    editor_notes.append(blk)
        elif section == "KP":
            if blk.kind == "BULLET":
                key_points.append(blk)
        elif section == "BIO":
            if blk.kind == "BIO_CALLOUT":
                guest_bios.append(blk)
        elif section == "CH" and cur_ch is not None:
            cur_ch.blocks.append(blk)

    return {
        "raw_text": raw_text,
        "eof_blank_lines": eof_blank_lines,
        "max_blanks": max_blanks,
        "blocks": blocks,
        "endnotes": endnote_blocks,
        "top_title": top_title,
        "epigraphs": epigraphs,
        "editor_notes": editor_notes,
        "key_points": key_points,
        "guest_bios": guest_bios,
        "chapters": chapters,
    }


def check_mode_b(
    md_path: Path,
    working_draft: Path | None = None,
    transcript_path: Path | None = None,
    pure_text: bool = False,
) -> list[CheckResult]:
    raw_text = md_path.read_text(encoding="utf-8")
    doc = parse_document(raw_text)
    results: list[CheckResult] = []

    err_shell: list[str] = []
    norm = raw_text.replace("\r\n", "\n")
    if re.search(r"(?m)^\s*---\s*$", norm):
        err_shell.append("检测到禁用的 '---' 分割线或 YAML Frontmatter")
    if re.search(r"(?m)^#{2,6}\s+", norm):
        err_shell.append("检测到禁用的 H2-H6 子标题（全篇只用单级 '#'）")
    if re.search(r"\[\[[^\[\]\n]+\]\]", norm):
        err_shell.append("检测到 Obsidian 双链 [[ ]]")
    if re.search(r"(?m)^(?:#\s+|\*\*)?(?:写在最后|本文来源|交接文档)", norm):
        err_shell.append("检测到已取消的 '写在最后/本文来源/交接文档' 区块")
    if pure_text and re.search(r"(?:🖼️|🎞️|📊|!\[[^\]]*\]\([^)]+\)|品牌图)", norm):
        err_shell.append("纯文字模式下检测到图片占位符或 Markdown 图片")

    if not doc["top_title"]:
        err_shell.append("缺少文首一级主标题 '# <中文标题>'")
    if len(doc["epigraphs"]) != 1:
        err_shell.append(f"开头题记 blockquote 应恰好 1 处，实际 {len(doc['epigraphs'])} 处")
    if len(doc["editor_notes"]) != 2:
        err_shell.append(f"编者按应为 2 段，实际 {len(doc['editor_notes'])} 段")
    else:
        ed_sents = len(SENTENCE_END_RE.findall("\n".join(b.text for b in doc["editor_notes"])))
        if ed_sents > 5:
            err_shell.append(f"编者按总句数应 ≤5 句，实际 {ed_sents} 句")
    if not (5 <= len(doc["key_points"]) <= 8):
        err_shell.append(f"'# 核心看点' 条目数应在 5-8 条之间，实际 {len(doc['key_points'])} 条")
    if len(doc["guest_bios"]) != 1 or not doc["guest_bios"][0].text.strip().startswith("> 💡 "):
        err_shell.append("'# 嘉宾背景' 应包含 1 个 '> 💡 姓名｜...' callout 块")
    if not (1 <= len(doc["chapters"]) <= 11):
        err_shell.append(f"正文章节 H1 数量应为 1-11 章，实际 {len(doc['chapters'])} 章")

    results.append(CheckResult(
        "MB.1", "共有壳与禁用结构检查",
        "FAIL" if err_shell else "PASS",
        f"共有壳完整（{len(doc['chapters'])} 章）" if not err_shell else f"发现 {len(err_shell)} 处结构问题",
        err_shell,
    ))

    err_fmt: list[str] = []
    if TIMESTAMP_BRACKET_RE.search(norm):
        err_fmt.append("发布版正文中仍残留 [MM:SS] 时间戳")
    if STAGE_DIR_RE.search(norm):
        err_fmt.append("发布版正文中残留 [笑]/[掌声] 舞台指示")
    if doc["max_blanks"] >= 3:
        err_fmt.append(f"连续空行最多允许 2 行，实际出现 {doc['max_blanks']} 行")

    blocks = doc["blocks"]
    for idx in range(1, len(blocks)):
        pk, ck = blocks[idx - 1].kind, blocks[idx].kind
        gap = blocks[idx].blank_before
        if pk == "BYLINE_1" and ck == "BYLINE_2" and gap != 0:
            err_fmt.append(f"第 {blocks[idx].start_line} 行：两行署名之间不应有空行")
        elif pk == "OTHER_H1" and gap != 2:
            err_fmt.append(f"第 {blocks[idx].start_line} 行：一级标题 '#' 之下必须空 2 行（实际空 {gap} 行）")
        elif ck == "SPEAKER_TAG" and gap != 2:
            err_fmt.append(f"第 {blocks[idx].start_line} 行：说话人标签之前必须空 2 行（实际空 {gap} 行）")
        elif pk == "SPEAKER_TAG" and ck == "SPEECH_PARA" and gap != 1:
            err_fmt.append(f"第 {blocks[idx].start_line} 行：说话人标签与发言之间必须空 1 行（实际空 {gap} 行）")

    host_tags = [b for ch in doc["chapters"] for b in ch.blocks if b.kind == "SPEAKER_TAG" and b.text.startswith("🎙️")]
    if host_tags:
        first_host = host_tags[0].text.strip()
        if not re.match(r"^🎙️ 主持人（.+）$", first_host):
            err_fmt.append(f"主持人首次标签应为 '🎙️ 主持人（全名）'，实际为 {first_host!r}")
        for ht in host_tags[1:]:
            if ht.text.strip() != "🎙️ 主持人":
                err_fmt.append(f"第 {ht.start_line} 行：主持人非首次标签应写 '🎙️ 主持人'")

    results.append(CheckResult(
        "MB.2", "去时间戳、空行状态机与说话人标签",
        "FAIL" if err_fmt else "PASS",
        "空行规则、说话人标签与零时间戳全部合规" if not err_fmt else f"发现 {len(err_fmt)} 处排版/标签问题",
        err_fmt[:20],
    ))

    err_tone: list[str] = []
    for term in TIER1_BANNED_19:
        if term in norm:
            err_tone.append(f"包含禁用 AI 腔/错别词：{term!r}")
    for term, hint in BANNED_GLOSSARY:
        if term in norm:
            err_tone.append(f"违反 glossary.md：{term!r}（{hint}）")
    if len(BUSHI_ERSHI_RE.findall(norm)) > 3:
        err_tone.append("全篇 '不是…而是…' 超过 3 处上限")
    for m in BAD_RANGE_DASH_RE.finditer(norm):
        err_tone.append(f"数字区间使用了非半角连字符 '-'：{m.group(0)!r}")
    if PERCENT_CJK_RE.search(norm):
        err_tone.append("百分比使用了汉字 '百分之...'，应使用阿拉伯数字 + '%'")

    for m in UNCOMMAD_INT_RE.finditer(norm):
        val = int(m.group(1))
        pre = norm[max(0, m.start() - 15) : m.start()]
        post = norm[m.end() : min(len(norm), m.end() + 10)]
        if 1800 <= val <= 2099 and (re.match(r"\s*(?:年|年代)", post) or re.search(r"(?:公元|在|自|到|至|截至)\s*$", pre)):
            continue
        if re.search(r"(?:第|编号|页码|ID[:：]?|#|[A-Za-z]+[-_\s]?)\s*$", pre):
            continue
        err_tone.append(f"≥1,000 的数字未加千分位逗号：{m.group(1)!r}")

    body_text = "\n".join(b.text for b in doc["blocks"])
    n_body_warn = body_text.count("⚠️")
    n_end_warn = sum(1 for b in doc["endnotes"] for ln in b.lines if "⚠️" in ln)
    if n_body_warn != n_end_warn:
        err_tone.append(f"正文 ⚠️ 数量（{n_body_warn}）与文末说明 ⚠️ 数量（{n_end_warn}）不一一对应")

    results.append(CheckResult(
        "MB.3", "零 AI 腔、数字千分位、术语表与 ⚠️ 对等性",
        "FAIL" if err_tone else "PASS",
        "零 AI 腔、术语表、千分位与 ⚠️ 1:1 对等全部通过" if not err_tone else f"发现 {len(err_tone)} 处语言/术语/数字违规",
        err_tone[:20],
    ))

    if working_draft is not None:
        err_wd: list[str] = []
        if not working_draft.is_file():
            err_wd.append(f"找不到带时间戳工作稿：{working_draft}")
        else:
            repo_root = Path(__file__).resolve().parent
            edit_script = repo_root / "check_transcript_edit.py"
            cmd = [sys.executable, "-B", str(edit_script), str(working_draft), "--json"]
            if transcript_path and transcript_path.is_file():
                cmd.extend(["--transcript", str(transcript_path)])
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                err_wd.append(f"check_transcript_edit.py 返回非零退出码 ({proc.returncode})")
            try:
                payload = json.loads(proc.stdout)
                if payload.get("timestamps", 0) <= 0:
                    err_wd.append("工作稿中未检测到 [MM:SS] 时间戳")
                if payload.get("reversals"):
                    err_wd.append(f"工作稿存在 {len(payload['reversals'])} 处时间戳逆序")
            except Exception as exc:
                err_wd.append(f"解析 check_transcript_edit.py JSON 失败：{exc}")

            w_lines = strip_timestamps_for_diff(working_draft.read_text(encoding="utf-8"))
            f_lines = normalize_lines_for_diff(raw_text)
            if w_lines != f_lines:
                diff = list(difflib.unified_diff(w_lines, f_lines, lineterm="", n=1))
                err_wd.append(f"工作稿剥离时间戳后与发布版存在差异：{diff[:10]}")

        results.append(CheckResult(
            "MB.4", "工作稿时间轴机检与剥离时间戳等价性",
            "FAIL" if err_wd else "PASS",
            "工作稿时间轴单调递增且剥离时间戳后与成品逐行零差异" if not err_wd else f"发现 {len(err_wd)} 处工作稿校验问题",
            err_wd,
        ))

    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="模式 B（对话体逐字稿）全量静态体检器")
    parser.add_argument("md_path", help="成品逐字稿 .md 路径")
    parser.add_argument("--working-draft", default=None, help="带时间戳工作稿 .md 路径")
    parser.add_argument("--transcript", default=None, help="原始字幕 transcript.json 路径")
    parser.add_argument("--pure-text", action="store_true", help="纯文字逐字稿模式（禁止任何图片占位符）")
    parser.add_argument("--json", action="store_true", dest="as_json", help="输出 JSON 格式报告")
    args = parser.parse_args(argv)

    md_path = Path(args.md_path)
    if not md_path.is_file():
        print(f"[ERROR] 找不到成品文件：{md_path}", file=sys.stderr)
        return 1

    wd_path = Path(args.working_draft) if args.working_draft else None
    tr_path = Path(args.transcript) if args.transcript else None

    results = check_mode_b(md_path, wd_path, tr_path, args.pure_text)
    failed = [r for r in results if r.status == "FAIL"]

    if args.as_json:
        print(json.dumps({
            "file": str(md_path),
            "verdict": "FAIL" if failed else "PASS",
            "results": [r.to_dict() for r in results],
        }, ensure_ascii=False, indent=2))
    else:
        for r in results:
            icon = "✅" if r.status == "PASS" else "❌"
            print(f"{icon} [{r.check_id}] {r.name}：{r.message}")
            for d in r.details:
                print(f"   - {d}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
