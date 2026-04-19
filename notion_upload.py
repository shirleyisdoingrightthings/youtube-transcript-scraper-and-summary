#!/opt/homebrew/bin/python3.11
"""
将 Blog Markdown 文件上传到 Notion Resources Library 数据库。
Usage: python3 notion_upload.py <markdown_file_path> <youtube_url>
"""

import sys
import re
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"
DATABASE_ID    = os.environ.get("NOTION_DATABASE_ID", "")

HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_VERSION,
}


# ───────────────────────────────────────────
# Markdown → Notion Blocks 转换
# ───────────────────────────────────────────

def rich_text(text: str) -> list:
    """把 **bold** 转成 Notion rich_text 格式"""
    parts = []
    for seg in re.split(r"(\*\*[^*]+\*\*)", text):
        if seg.startswith("**") and seg.endswith("**"):
            parts.append({
                "type": "text",
                "text": {"content": seg[2:-2]},
                "annotations": {"bold": True},
            })
        elif seg:
            parts.append({"type": "text", "text": {"content": seg}})
    return parts or [{"type": "text", "text": {"content": text}}]


def heading_block(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def image_block(url: str) -> dict:
    return {"object": "block", "type": "image",
            "image": {"type": "external", "external": {"url": url}}}


def paragraph_block(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(text)}}


def bullet_block(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rich_text(text)}}


def divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def quote_block(text: str) -> dict:
    return {"object": "block", "type": "quote",
            "quote": {"rich_text": rich_text(text)}}


def parse_markdown(content: str) -> tuple[str, list]:
    """返回 (页面标题, notion_blocks列表)"""
    blocks: list[dict] = []
    title = "YouTube 视频解读"
    lines = content.split("\n")
    i = 0

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # ── 空行 ──
        if not line:
            i += 1
            continue

        # ── 分隔线 ──
        if re.match(r"^-{3,}$", line):
            blocks.append(divider_block())

        # ── H1 ──
        elif re.match(r"^#\s+", line):
            text = re.sub(r"^#\s+", "", line)
            if title == "YouTube 视频解读":
                title = text          # 第一个 H1 作为页面标题
            blocks.append(heading_block(1, text))

        # ── H2 ──
        elif re.match(r"^##\s+", line):
            blocks.append(heading_block(2, re.sub(r"^##\s+", "", line)))

        # ── H3 ──
        elif re.match(r"^###\s+", line):
            blocks.append(heading_block(3, re.sub(r"^###\s+", "", line)))

        # ── H4 ──
        elif re.match(r"^####\s+", line):
            blocks.append(heading_block(4, re.sub(r"^####\s+", "", line)))

        # ── 引用 ──
        elif re.match(r"^>\s+", line):
            blocks.append(quote_block(re.sub(r"^>\s+", "", line)))

        # ── 无序列表 ──
        elif re.match(r"^[-*•]\s+", line):
            blocks.append(bullet_block(re.sub(r"^[-*•]\s+", "", line)))

        # ── 有序列表 ──
        elif re.match(r"^\d+\.\s+", line):
            blocks.append(bullet_block(re.sub(r"^\d+\.\s+", "", line)))

        # ── 普通段落（合并连续行）──
        else:
            para_lines = [line]
            while (i + 1 < len(lines)
                   and lines[i + 1].strip()
                   and not re.match(r"^[#>\-*•]|\d+\.", lines[i + 1].strip())):
                i += 1
                para_lines.append(lines[i].strip())
            text = " ".join(para_lines)
            # Notion 单块最多 2000 字符
            for chunk in [text[j: j + 2000] for j in range(0, len(text), 2000)]:
                blocks.append(paragraph_block(chunk))

        # ── 从 Metadata 里提取标题（备用）──
        if title == "YouTube 视频解读":
            m = re.search(r"\*\*视频标题[：:]\*\*\s*(.+)", line)
            if m:
                title = m.group(1).strip()

        i += 1

    return title, blocks


# ───────────────────────────────────────────
# Notion API 操作
# ───────────────────────────────────────────

def create_page(title: str, youtube_url: str) -> str:
    """在数据库里新建一页，返回 page_id"""
    today = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Name":         {"title": [{"type": "text", "text": {"content": title}}]},
            "URL":          {"url": youtube_url},
            "Type":         {"select": {"name": "视频"}},
            "Category":     {"multi_select": [{"name": "播客访谈"}]},
            "Created Date": {"date": {"start": today}},
            "Status":       {"status": {"name": "Not started"}},
        },
    }
    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS, json=payload, timeout=30,
    )
    if not resp.ok:
        print(f"[ERROR] 创建页面失败: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()["id"]


def append_blocks(page_id: str, blocks: list) -> None:
    """分批上传 blocks（每批最多 95 个）"""
    for i in range(0, len(blocks), 95):
        chunk = blocks[i: i + 95]
        resp = requests.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=HEADERS, json={"children": chunk}, timeout=30,
        )
        if not resp.ok:
            print(f"[ERROR] 上传 blocks 失败: {resp.status_code} {resp.text}")
            sys.exit(1)


# ───────────────────────────────────────────
# 主流程
# ───────────────────────────────────────────

def main():
    if not NOTION_API_KEY or not DATABASE_ID:
        print("[ERROR] NOTION_API_KEY or NOTION_DATABASE_ID not set in .env")
        sys.exit(1)
    if len(sys.argv) < 3:
        print("Usage: notion_upload.py <markdown_file> <youtube_url>")
        sys.exit(1)

    md_path     = sys.argv[1]
    youtube_url = sys.argv[2]

    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    title, blocks = parse_markdown(content)

    # 在内容最前面插入视频封面图
    vid_match = re.search(r"(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})", youtube_url)
    if vid_match:
        thumbnail_url = f"https://img.youtube.com/vi/{vid_match.group(1)}/maxresdefault.jpg"
        blocks.insert(0, image_block(thumbnail_url))

    print(f"📄 标题：{title}")
    print(f"📦 共 {len(blocks)} 个块")

    print("🔗 正在创建 Notion 页面...")
    page_id = create_page(title, youtube_url)

    print("⬆️  正在上传内容...")
    append_blocks(page_id, blocks)

    clean_id = page_id.replace("-", "")
    print(f"✅ 完成！页面链接：https://notion.so/{clean_id}")


if __name__ == "__main__":
    main()
