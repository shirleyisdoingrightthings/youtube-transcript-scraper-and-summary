#!/opt/homebrew/bin/python3.11
"""
将 Blog Markdown 文件上传到 Notion Resources Library 数据库。
Usage: python3 notion_upload.py <markdown_file_path> <youtube_url>
"""
from __future__ import annotations

import sys
import re
import os
import requests
from datetime import datetime
from dotenv import load_dotenv

import http_utils

load_dotenv()

NOTION_API_KEY = os.environ.get("NOTION_API_KEY", "")
NOTION_VERSION = "2022-06-28"
# 文件上传（File Upload API）与引用 file_upload 的块，2022-06-28 那版根本没有，
# 必须用新版本号。只在这三处请求上用它，数据库查重 / 建页仍走旧版本——
# 2025-09-03 起 database 改成了 data source 语义，全局升版会连带打断查重。
NOTION_UPLOAD_VERSION = "2026-03-11"
FILE_UPLOAD_MAX_BYTES = 20 * 1024 * 1024      # 单文件上限 20 MB
DATABASE_ID    = os.environ.get("NOTION_DATABASE_ID", "")

HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_VERSION,
}

UPLOAD_HEADERS = {
    "Authorization":  f"Bearer {NOTION_API_KEY}",
    "Content-Type":   "application/json",
    "Notion-Version": NOTION_UPLOAD_VERSION,
}


# ───────────────────────────────────────────
# Markdown → Notion Blocks 转换
# ───────────────────────────────────────────

# Notion 单个 rich_text 的 content 上限 2000 字符（超了直接 400）
TEXT_LIMIT = 2000

# 行内语法：反引号最先，避免代码里的 * 被当成加粗；双链先于普通链接
INLINE_RE = re.compile(
    r"(?P<code>`[^`\n]+`)"
    r"|(?P<bold>\*\*.+?\*\*)"
    r"|(?P<wiki>\[\[[^\[\]\n]+\]\])"
    r"|(?P<link>\[[^\[\]\n]+\]\([^()\s]+\))"
)


def _text_items(content: str, *, bold: bool = False, code: bool = False,
                link: str | None = None) -> list:
    """生成一个或多个 rich_text 项，超过 2000 字符按上限切分"""
    items = []
    chunks = [content[i: i + TEXT_LIMIT]
              for i in range(0, len(content), TEXT_LIMIT)] or [content]
    for chunk in chunks:
        item: dict = {"type": "text", "text": {"content": chunk}}
        if link:
            item["text"]["link"] = {"url": link}
        annotations = {}
        if bold:
            annotations["bold"] = True
        if code:
            annotations["code"] = True
        if annotations:
            item["annotations"] = annotations
        items.append(item)
    return items


def rich_text(text: str) -> list:
    """把行内 Markdown 转成 Notion rich_text。

    支持：**加粗**、`行内代码`、[文字](链接)、[[双链]]（Obsidian 专用语法，
    上传 Notion 时剥掉方括号只留词条本身，否则页面上会出现 [[…]] 噪音）。
    """
    parts: list = []
    pos = 0
    for m in INLINE_RE.finditer(text):
        if m.start() > pos:
            parts += _text_items(text[pos: m.start()])
        kind = m.lastgroup
        raw = m.group()
        if kind == "code":
            parts += _text_items(raw[1:-1], code=True)
        elif kind == "bold":
            parts += _text_items(raw[2:-2], bold=True)
        elif kind == "wiki":
            # [[词条]] / [[词条|显示文字]] → 只保留人读的那部分
            inner = raw[2:-2]
            parts += _text_items(inner.split("|")[-1].strip())
        elif kind == "link":
            label, url = re.match(r"\[([^\]]+)\]\(([^)]+)\)", raw).groups()
            parts += _text_items(label, link=url)
        pos = m.end()
    if pos < len(text):
        parts += _text_items(text[pos:])
    return parts or _text_items(text)


def heading_block(level: int, text: str) -> dict:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def image_block(url: str) -> dict:
    return {"object": "block", "type": "image",
            "image": {"type": "external", "external": {"url": url}}}


def uploaded_image_block(file_upload_id: str) -> dict:
    """引用已上传到 Notion 的文件。图由 Notion 自己托管，不需要图床。"""
    return {"object": "block", "type": "image",
            "image": {"type": "file_upload", "file_upload": {"id": file_upload_id}}}


# 解析阶段先占位、不联网：本地图片的上传统一放到 resolve_local_images() 里做，
# 这样 parse_markdown() 保持纯函数，测试不用起网络。
LOCAL_IMAGE_TYPE = "_local_image"


def local_image_placeholder(path: str, alt: str) -> dict:
    return {"object": "block", "type": "image",
            "image": {"type": LOCAL_IMAGE_TYPE,
                      LOCAL_IMAGE_TYPE: {"path": path, "alt": alt}}}


def is_local_image(block: dict) -> bool:
    return (block.get("type") == "image"
            and block.get("image", {}).get("type") == LOCAL_IMAGE_TYPE)


# Notion code block 只认固定的语言枚举，不在表里的一律降级为 plain text
CODE_LANGUAGES = {
    "python", "javascript", "typescript", "bash", "shell", "json", "yaml",
    "markdown", "html", "css", "sql", "java", "go", "rust", "c", "c++", "diff",
}
CODE_LANG_ALIASES = {"js": "javascript", "ts": "typescript", "sh": "bash",
                     "zsh": "bash", "yml": "yaml", "md": "markdown", "text": "plain text"}


def code_block(body: str, lang: str = "") -> dict:
    language = CODE_LANG_ALIASES.get(lang.lower(), lang.lower())
    if language not in CODE_LANGUAGES:
        language = "plain text"
    return {"object": "block", "type": "code",
            "code": {"rich_text": _text_items(body), "language": language}}


def paragraph_block(text: str) -> dict:
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": rich_text(text)}}


def bullet_block(text: str) -> dict:
    return {"object": "block", "type": "bulleted_list_item",
            "bulleted_list_item": {"rich_text": rich_text(text)}}


def numbered_block(text: str) -> dict:
    # Notion 按相邻的 numbered_list_item 自动编号，源文件里写的 1. 2. 数字不传上去
    return {"object": "block", "type": "numbered_list_item",
            "numbered_list_item": {"rich_text": rich_text(text)}}


def divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def quote_block(text: str) -> dict:
    return {"object": "block", "type": "quote",
            "quote": {"rich_text": rich_text(text)}}


# skill 里规定的三种减负装置 / 增补装置，用 Notion callout 承载才有视觉层级：
#   📍 路线条（illustrated_deepdive「本文路线」）
#   💡 说人话保底句
#   🔍 名词解释灰框（reader_facing_review 的编者增补，必须与嘉宾原话区分开）
CALLOUT_ICONS = ("📍", "💡", "🔍")


def table_block(rows: list, has_column_header: bool = True) -> dict:
    """Markdown 表格 → Notion table 块。

    rows 是二维字符串数组（已剔除 |---|---| 分隔行）。Notion 要求每行单元格数
    与 table_width 一致，短行补空、长行截断，否则整块会被 API 拒掉。
    """
    width = max(len(r) for r in rows)
    children = []
    for r in rows:
        cells = [rich_text(c) for c in r[:width]]
        cells += [[] for _ in range(width - len(cells))]
        children.append({
            "object": "block", "type": "table_row",
            "table_row": {"cells": cells},
        })
    return {
        "object": "block", "type": "table",
        "table": {
            "table_width": width,
            "has_column_header": has_column_header,
            "has_row_header": False,
            "children": children,
        },
    }


def _split_callout(line: str) -> tuple:
    """行首是 callout emoji（允许写成 `> 📍 …` 的灰框形式）则返回 (icon, 正文)。"""
    body = re.sub(r"^>\s*", "", line)
    for icon in CALLOUT_ICONS:
        if body.startswith(icon):
            return icon, body[len(icon):].lstrip("️").lstrip()
    return None, line


def callout_block(text: str, icon: str) -> dict:
    return {"object": "block", "type": "callout",
            "callout": {"rich_text": rich_text(text),
                        "icon": {"type": "emoji", "emoji": icon},
                        "color": "gray_background"}}


def parse_markdown(content: str) -> tuple[str, list]:
    """返回 (页面标题, notion_blocks列表)"""
    blocks: list[dict] = []
    title = "YouTube 视频解读"
    lines = content.split("\n")
    i = 0

    # ── 跳过 YAML Frontmatter ──
    if len(lines) > 0 and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1  # 略过闭合的 ---

    while i < len(lines):
        raw = lines[i]
        line = raw.strip()

        # ── 空行 ──
        # 单个空行只是分块，不产生内容；**连续 ≥2 个空行**表示作者想要一段视觉留白，
        # 在 Notion 里落一个空段落块（Markdown 的普通空行到 Notion 是不留痕的）。
        if not line:
            blank_run = 0
            while i < len(lines) and not lines[i].strip():
                blank_run += 1
                i += 1
            # 文档开头与结尾不留空块，避免首尾出现莫名其妙的空行
            if blank_run >= 2 and blocks and i < len(lines):
                blocks.append(paragraph_block(""))
            continue

        # ── Markdown 表格（连续的 | 行；分隔行 |---|---| 丢弃）──
        if line.startswith("|") and line.endswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cur = lines[i].strip().strip("|")
                if not re.fullmatch(r"[\s:\-|]+", cur):
                    rows.append([c.strip() for c in cur.split("|")])
                i += 1
            if rows:
                blocks.append(table_block(rows))
            continue

        # ── 围栏代码块（``` 起 ``` 止；封面 Recraft Prompt 就住在这里）──
        if line.startswith("```"):
            lang = line[3:].strip()
            body_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body_lines.append(lines[i])
                i += 1
            blocks.append(code_block("\n".join(body_lines), lang))
            i += 1          # 吃掉收尾的 ```
            continue

        # ── Callout（📍 路线条 / 💡 说人话 / 🔍 名词解释；允许 `> ` 开头的灰框写法）──
        icon, callout_text = _split_callout(line)
        if icon:
            # 换行续写的部分并进同一个 callout，别被拆成孤立段落
            while (i + 1 < len(lines)
                   and lines[i + 1].strip()
                   and not re.match(r"^([#>\-*•|`!]|\d+\.)", lines[i + 1].strip())
                   and not _split_callout(lines[i + 1].strip())[0]):
                i += 1
                callout_text += " " + lines[i].strip()
            blocks.append(callout_block(callout_text, icon))
            i += 1
            continue

        # ── 分隔线 ──
        if re.match(r"^-{3,}$", line):
            blocks.append(divider_block())

        # ── 图片：![alt](url)，仅 http(s) 外链能进 Notion image block ──
        elif re.fullmatch(r"!\[[^\]]*\]\([^)]+\)", line):
            alt, src = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", line).groups()
            if src.startswith(("http://", "https://")):
                blocks.append(image_block(src))
            else:
                # 本地路径先占位，稍后由 resolve_local_images() 上传成 file_upload；
                # 上传不成或文件不存在时再降级成一行提示文字。
                blocks.append(local_image_placeholder(src, alt))

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

        # ── 有序列表 ──（此前误转成无序列表，编号在 Notion 里会丢）
        elif re.match(r"^\d+\.\s+", line):
            blocks.append(numbered_block(re.sub(r"^\d+\.\s+", "", line)))

        # ── 普通段落（合并连续行）──
        else:
            para_lines = [line]
            # 表格行 / 代码围栏 / 图片行不并进段落，否则会被空格粘成一坨
            while (i + 1 < len(lines)
                   and lines[i + 1].strip()
                   and not re.match(r"^([#>\-*•|`!]|\d+\.)", lines[i + 1].strip())):
                i += 1
                para_lines.append(lines[i].strip())
            # 2000 字符上限由 rich_text 内部按片切分，这里不再按字数切块——
            # 按字数硬切会把 **加粗** 从中间劈开
            blocks.append(paragraph_block(" ".join(para_lines)))

        # ── 从 Metadata 里提取标题（备用）──
        if title == "YouTube 视频解读":
            m = re.search(r"\*\*视频标题\*\*\s*[:：]\s*(.+)", line)
            if not m:
                m = re.search(r"\*\*视频标题[：:]\*\*\s*(.+)", line)
            if m:
                title = m.group(1).strip()

        i += 1

    return title, blocks


# ───────────────────────────────────────────
# Notion API 操作
# ───────────────────────────────────────────

def find_pages_by_url(youtube_url: str) -> list:
    """查询数据库中所有关联该 URL 的活跃页面，返回 [(page_id, title), ...]"""
    resp = http_utils.post(
        f"https://api.notion.com/v1/databases/{DATABASE_ID}/query",
        headers=HEADERS,
        json={"filter": {"property": "URL", "url": {"equals": youtube_url}}},
        timeout=30,
    )
    if not resp.ok:
        return []
    results = resp.json().get("results", [])
    pages = []
    for page in results:
        pid = page["id"]
        title_parts = page["properties"]["Name"]["title"]
        t = title_parts[0]["plain_text"] if title_parts else ""
        pages.append((pid, t))
    return pages


def archive_page(page_id: str) -> None:
    """将已有页面归档（软删除），为重新上传腾位"""
    http_utils.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"archived": True},
        timeout=30,
    )


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
    resp = http_utils.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS, json=payload, timeout=30,
    )
    if not resp.ok:
        print(f"[ERROR] 创建页面失败: {resp.status_code} {resp.text}")
        sys.exit(1)
    return resp.json()["id"]


# ───────────────────────────────────────────
# 本地图片 → Notion File Upload
# ───────────────────────────────────────────

MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
}

# 同一次运行里同一张图只传一次（正文里同图多处引用很常见）
_upload_cache: dict[str, str] = {}


def upload_local_file(path: str) -> str:
    """把本地文件传给 Notion，返回 file_upload id。失败抛异常，由调用方降级。

    三步：建 file_upload 对象 → 把字节 POST 到 send 端点 → 拿 id 去引用。
    id 有效期 1 小时，必须在这段时间内挂到块上，所以上传放在建页之后、贴块之前。
    """
    real = os.path.abspath(path)
    if real in _upload_cache:
        return _upload_cache[real]

    size = os.path.getsize(real)
    if size > FILE_UPLOAD_MAX_BYTES:
        raise RuntimeError(f"文件 {size // 1024 // 1024} MB，超过单文件 20 MB 上限")

    name = os.path.basename(real)
    mime = MIME_BY_EXT.get(os.path.splitext(name)[1].lower(), "application/octet-stream")

    resp = http_utils.post(
        "https://api.notion.com/v1/file_uploads",
        headers=UPLOAD_HEADERS, json={}, timeout=30, label="file_upload.create",
    )
    if not resp.ok:
        raise RuntimeError(f"创建 file_upload 失败: {resp.status_code} {resp.text}")
    obj = resp.json()
    upload_id = obj["id"]

    # send 端点是 multipart，不能带 Content-Type: application/json，
    # 也不能自己拼 boundary——交给 requests 的 files= 去生成。
    send_headers = {k: v for k, v in UPLOAD_HEADERS.items() if k != "Content-Type"}
    with open(real, "rb") as fh:
        payload = fh.read()      # 读进内存再发：文件句柄发完就到 EOF，重试会传出 0 字节
    resp = http_utils.post(
        obj.get("upload_url") or f"https://api.notion.com/v1/file_uploads/{upload_id}/send",
        headers=send_headers, files={"file": (name, payload, mime)},
        timeout=60, label="file_upload.send",
    )
    if not resp.ok:
        raise RuntimeError(f"上传文件内容失败: {resp.status_code} {resp.text}")

    _upload_cache[real] = upload_id
    return upload_id


def resolve_local_images(blocks: list, base_dir: str, uploader=None) -> list:
    """把解析阶段留下的本地图片占位块换成真正的 file_upload 引用。

    找不到文件、或上传失败，都降级成一行提示文字——**绝不把占位块原样发出去**，
    那种块 Notion 不认，整批 95 个块会一起 400。
    """
    up = uploader or upload_local_file
    out = []
    for b in blocks:
        if not is_local_image(b):
            out.append(b)
            continue
        info = b["image"][LOCAL_IMAGE_TYPE]
        src, alt = info["path"], info.get("alt", "")
        full = src if os.path.isabs(src) else os.path.join(base_dir, src)
        if not os.path.isfile(full):
            print(f"⚠️  图片不存在，降级成占位文字：{src}")
            out.append(paragraph_block(f"🖼️ [待补图片：{alt or src}]"))
            continue
        try:
            out.append(uploaded_image_block(up(full)))
            print(f"  ↑ 已上传 {os.path.basename(full)}")
        except Exception as e:                      # noqa: BLE001 —— 上传失败不该拖垮整篇
            print(f"⚠️  上传失败，降级成占位文字：{src}（{e}）")
            out.append(paragraph_block(f"🖼️ [待补图片：{alt or src}]"))
    return out


def has_uploaded_image(blocks: list) -> bool:
    return any(b.get("type") == "image"
               and b.get("image", {}).get("type") == "file_upload" for b in blocks)


def append_blocks(page_id: str, blocks: list) -> None:
    """分批上传 blocks（每批最多 95 个）。失败抛异常，交给调用方收拾空页。"""
    for i in range(0, len(blocks), 95):
        chunk = blocks[i: i + 95]
        # 引用 file_upload 的块旧版本号不认，这一批就换新版本发；
        # 其余批次维持 2022-06-28，避免升版牵动查重与建页。
        headers = UPLOAD_HEADERS if has_uploaded_image(chunk) else HEADERS
        resp = http_utils.patch(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers, json={"children": chunk}, timeout=30,
        )
        if not resp.ok:
            raise RuntimeError(f"上传 blocks 失败: {resp.status_code} {resp.text}")


# ───────────────────────────────────────────
# 防冲突逻辑
# ───────────────────────────────────────────

# 当前四种产物类型在前；"深度文章"为已退役类型，仅保留识别能力以兼容历史文件。
# 新增一种产物形态时，只需在这里登记类型名。
TYPE_NAMES = ("图文精读", "逐字稿", "演讲实录", "观察稿", "深度文章")

# 文件名里出现过的几种分隔写法都要认；按长度降序匹配，避免 "-" 抢先吃掉 " - "
SEPARATORS = (" — ", " - ", "—", "-")


def canonical_suffix(type_name: str) -> str:
    """统一的后缀写法：全角破折号 + 类型名"""
    return f"—{type_name}"


def detect_type_suffix(title: str) -> tuple:
    """
    从标题中提取 (base_title, canonical_type_suffix)。
    识别不出类型时返回 (原标题, None)。
    例：'Dylan Patel｜... - 逐字稿' → ('Dylan Patel｜...', '—逐字稿')
    """
    for type_name in TYPE_NAMES:
        for sep in SEPARATORS:
            suffix = f"{sep}{type_name}"
            if title.endswith(suffix):
                return title[: -len(suffix)].rstrip(), canonical_suffix(type_name)
    return title, None


def resolve_dedup(youtube_url: str, base_title: str, current_suffix: str) -> str:
    """
    防冲突核心逻辑，返回最终使用的页面标题。

    页面标题一律自带类型后缀（含首次上传），这样线上每一页都自证类型，
    不需要靠"推断另一种类型"去猜——猜错会给旧页贴上错误的后缀。

    规则：
    1. 线上已有同类型页（base + 当前后缀）→ 归档旧页，新建（更新语义）
    2. 线上已有其他类型页 → 不动它
    3. 线上有无类型后缀的历史页 → 无法判定其类型，保留不动并告警，交人工处理
    """
    final_title = f"{base_title}{current_suffix}"
    existing_pages = find_pages_by_url(youtube_url)

    if not existing_pages:
        print(f"📌 首次上传，标题：{final_title}")
        return final_title

    for pid, ptitle in existing_pages:
        p_base, p_suffix = detect_type_suffix(ptitle)

        if p_suffix == current_suffix and p_base == base_title:
            # 规则 1：同类型重复上传 → 归档旧版
            print("♻️  同类型页面已存在，归档旧版本...")
            archive_page(pid)

        elif p_suffix is None and p_base == base_title:
            # 规则 3：历史遗留的无后缀页，类型不可知 → 绝不猜
            print(f"⚠️  线上存在一页无类型后缀的历史页「{ptitle}」，无法判定它属于哪种产物，已保留不动。")
            print("    若它其实就是本次这一类，请在 Notion 手动归档后重传，避免留下重复页。")

        # 规则 2：其他类型的页面 → 不动

    return final_title


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

    _, blocks = parse_markdown(content)
    blocks = resolve_local_images(blocks, os.path.dirname(os.path.abspath(md_path)))

    # 从文件名提取标题与类型
    basename = os.path.basename(md_path)
    filename_title = basename[:-3] if basename.endswith(".md") else basename
    base_title, current_suffix = detect_type_suffix(filename_title)

    # 如果无法从文件名识别类型，直接用文件名作标题（此时查重无从判断，只能跳过）
    if current_suffix is None:
        print(f"⚠️  文件名未带已知类型后缀（{'/'.join(TYPE_NAMES[:4])}），本次跳过查重，"
              f"重传会留下重复页。建议把文件名改成「<标题> - <类型>.md」。")
        title = filename_title
    else:
        title = resolve_dedup(youtube_url, base_title, current_suffix)

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
    try:
        append_blocks(page_id, blocks)
    except RuntimeError as e:
        # 内容没传上去就留个空壳页，会被下次查重误判成"旧版本"，先清掉
        print(f"[ERROR] {e}")
        print("🧹 正在归档本次创建的空页面，避免留下空壳...")
        archive_page(page_id)
        sys.exit(1)

    clean_id = page_id.replace("-", "")
    print(f"✅ 完成！页面链接：https://notion.so/{clean_id}")


if __name__ == "__main__":
    main()
