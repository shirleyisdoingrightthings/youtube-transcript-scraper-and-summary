#!/usr/bin/env python3
"""
从 Notion 读回页面内容（终校 / 二次复核 / Agent Council 用）。

Usage:
    python3 notion_read.py <page_id_or_url>

作用：
    用 .env 里的 NOTION_API_KEY（与 notion_upload.py 同一个集成
    "claude code youtube transcript scraper and summary"）把【已上传/已编辑】的
    Notion 页面拉回本地纯文本，便于：
      - 对照字幕做终校；
      - 喂给 Agent Council 的评审 / 核实 Agent（务必喂完整正文，勿喂压缩摘要）。

⚠️ 访问权限坑（务必知道）：
    页面必须"连接(Connection)"给上述集成才读得到。
    - notion_upload.py 新建在 Resource Library 数据库里的页面，集成自带访问权；
    - 但一旦页面被【移出该数据库】（挪进个人空间），集成立即失去访问权，
      本脚本会返回 404 object_not_found；
    - 解决：在 Notion 打开该页 → 右上角 ••• → Connections →
      添加 "claude code youtube transcript scraper and summary"，即可恢复读取/写入。
    - 系统代理（127.0.0.1:7897）偶发 SSL 中断，请求走 http_utils 的统一退避重试。

输出：纯文本（标题 + 各 block，按层级缩进；图片/视频标 [IMAGE]/[VIDEO]）。
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

import http_utils

load_dotenv()

KEY = os.environ.get("NOTION_API_KEY", "")
HEADERS = {"Authorization": f"Bearer {KEY}", "Notion-Version": "2022-06-28"}


def _get(url: str):
    """GET with retries——退避策略与 fetch/upload 统一，见 http_utils。"""
    return http_utils.get(url, headers=HEADERS, timeout=30, label="notion-read")


def _rich_text(arr, *, markdown: bool = True) -> str:
    """还原为 Markdown。默认保留加粗 / 行内代码 / 链接——读回线上稿再落回本地时，
    只取 plain_text 会把编辑在 Notion 里做的重点标记全部丢掉。"""
    if not arr:
        return ""
    out = []
    for x in arr:
        s = x.get("plain_text", "")
        if not s:
            continue
        if markdown:
            ann = x.get("annotations", {})
            # 前后空白留在标记外面，否则 **  加粗 ** 在 Markdown 里不生效
            lead = s[: len(s) - len(s.lstrip())]
            trail = s[len(s.rstrip()):]
            core = s.strip()
            if core:
                if ann.get("code"):
                    core = f"`{core}`"
                if ann.get("bold"):
                    core = f"**{core}**"
                if ann.get("italic"):
                    core = f"*{core}*"
                href = x.get("href")
                if href:
                    core = f"[{core}]({href})"
            s = lead + core + trail
        out.append(s)
    return "".join(out)


def _block_text(b: dict) -> str:
    t = b["type"]
    d = b.get(t, {})
    if "rich_text" in d:
        prefix = {
            "heading_1": "# ", "heading_2": "## ", "heading_3": "### ",
            "bulleted_list_item": "- ", "numbered_list_item": "1. ",
            "quote": "> ", "to_do": "[] ", "callout": "💡 ",
            "toggle": "▸ ", "paragraph": "",
        }.get(t, "")
        return prefix + _rich_text(d["rich_text"])
    if t == "divider":
        return "---"
    if t == "image":
        cap = _rich_text(d.get("caption", []))
        return "[IMAGE]" + (f" cap:{cap}" if cap else "")
    if t in ("video", "embed", "bookmark"):
        return f"[{t.upper()}]"
    if t == "child_page":
        return "[child_page: %s]" % b.get("child_page", {}).get("title", "")
    return "[%s]" % t


def fetch_children(block_id: str, depth: int = 0, out: list | None = None) -> list:
    if out is None:
        out = []
    url = f"https://api.notion.com/v1/blocks/{block_id}/children?page_size=100"
    while url:
        r = _get(url)
        if not r.ok:
            out.append("  " * depth + f"[ERROR {r.status_code}: {r.text[:160]}]")
            return out
        j = r.json()
        for b in j.get("results", []):
            out.append("  " * depth + _block_text(b))
            if b.get("has_children") and b["type"] not in ("child_page", "child_database"):
                fetch_children(b["id"], depth + 1, out)
        if j.get("has_more"):
            url = (f"https://api.notion.com/v1/blocks/{block_id}/children"
                   f"?page_size=100&start_cursor={j['next_cursor']}")
        else:
            url = None
    return out


def page_title(page_id: str) -> str:
    r = _get(f"https://api.notion.com/v1/pages/{page_id}")
    if not r.ok:
        return f"[meta ERROR {r.status_code}]"
    for _, v in r.json().get("properties", {}).items():
        if v.get("type") == "title":
            return _rich_text(v["title"])
    return "(untitled)"


def _normalize_id(s: str) -> str:
    """从 URL 或带横杠 ID 里抽出 32 位 page id。

    注意：不能对整条 URL 做 replace("-","") ——slug 末尾若是 hex 字符
    （如 "Anthropic" 的 c）会被粘到真实 id 前面，导致取错 32 位。
    """
    import re
    s = s.split("?")[0].split("#")[0]
    # ① 优先匹配带横杠的标准 UUID
    m = re.search(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
        r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", s)
    if m:
        return m.group(0).replace("-", "")
    # ② 取最后一段路径里的尾部 32 位 hex（id 总在末尾，取末 32 位可避开 slug 粘连）
    tail = s.rstrip("/").split("/")[-1]
    hexonly = re.sub(r"[^0-9a-fA-F]", "", tail)
    if len(hexonly) >= 32:
        return hexonly[-32:]
    m = re.search(r"([0-9a-fA-F]{32})", s.replace("-", ""))
    return m.group(1) if m else s


def main():
    if not KEY:
        print("[ERROR] NOTION_API_KEY not set in .env")
        sys.exit(1)
    if len(sys.argv) < 2:
        print("Usage: python3 notion_read.py <page_id_or_url>")
        sys.exit(1)
    pid = _normalize_id(sys.argv[1])
    print("TITLE:", page_title(pid))
    print("=" * 70)
    print("\n".join(fetch_children(pid)))


if __name__ == "__main__":
    main()
