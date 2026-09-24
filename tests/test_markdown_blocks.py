"""Markdown → Notion blocks 转换的回归测试。

守的是这些"内容会悄悄变形"的老毛病：代码块 / 图片 / 双链 / 行内链接全部以
字面文本上墙；2000 字符按块硬切会把 **加粗** 从中间劈开；表格行被空格粘成一坨。
"""
from _bootstrap import check

import notion_upload as nu

MD = """---
tags:
  - 对话访谈
---

# 张三｜某主题

## 封面 Recraft Prompt

```text
A minimal editorial cover, muted palette,
no text, 16:9
```

## 正文

这里提到 [[Agent架构]] 和 [[HarnessEngineering|harness]]，还有 **加粗金句** 与 `inline_code`。
详见 [官方文档](https://example.com/docs)。

📍 本文路线：开场 → 论证 → 落点
继续写在下一行的路线说明

💡 说人话：这段的结论就是一句话。

> 🔍 名词解释 · JEPA：一种预测性架构。

![封面图](https://img.youtube.com/vi/abc/maxresdefault.jpg)

![本地占位](./cover.png)

| 维度 | 分数 |
| --- | --- |
| 传播度 | 8 |

> 一句被引用的话，含 **加粗**。

- 列表项含 [[双链]]
"""


def _flat(block):
    key = block["type"]
    return "".join(r["text"]["content"] for r in block.get(key, {}).get("rich_text", []))


def test_block_conversion():
    title, blocks = nu.parse_markdown(MD)
    types = [b["type"] for b in blocks]
    check(title == "张三｜某主题", "第一个 H1 作为页面标题", title)

    code = [b for b in blocks if b["type"] == "code"]
    check(len(code) == 1 and "A minimal editorial cover" in _flat(code[0])
          and "```" not in _flat(code[0]) and code[0]["code"]["language"] == "plain text",
          "围栏代码块 → Notion code block，反引号不上墙", types)

    ext = [b for b in blocks if b["type"] == "image" and b["image"]["type"] == "external"]
    check(len(ext) == 1 and ext[0]["image"]["external"]["url"].startswith("https://img.youtube.com"),
          "http(s) 图片 → external image block")

    # 本地路径不再当场降级：先留内部占位块，由 resolve_local_images() 上传成
    # file_upload，传不成再降级。详见 tests/test_notion_images.py。
    local = [b for b in blocks if nu.is_local_image(b)]
    check(len(local) == 1 and local[0]["image"][nu.LOCAL_IMAGE_TYPE]["path"] == "./cover.png",
          "本地路径图片 → 留成内部占位块，等待上传", local)

    body = [b for b in blocks if b["type"] == "paragraph" and "Agent" in _flat(b)][0]
    text = _flat(body)
    check("[[" not in text and "Agent架构" in text and "harness" in text
          and "HarnessEngineering" not in text,
          "[[双链]] 剥掉方括号、只留人读的那部分", text[:40])

    anns = [(r["text"]["content"], r.get("annotations"), r["text"].get("link"))
            for r in body["paragraph"]["rich_text"]]
    check(("加粗金句", {"bold": True}, None) in anns and ("inline_code", {"code": True}, None) in anns,
          "加粗 / 行内代码带上正确注解")

    link = [b for b in blocks if b["type"] == "paragraph" and "官方文档" in _flat(b)][0]
    urls = [r["text"]["link"]["url"] for r in link["paragraph"]["rich_text"] if r["text"].get("link")]
    check(urls == ["https://example.com/docs"] and "https://" not in _flat(link),
          "行内链接 → 真链接，URL 不再裸露在正文", urls)

    # 表格：Markdown 表格要变成 Notion 原生 table 块，而不是一堆带竖线的段落。
    # （旧行为是「每行各自成段」，2026-09-02 升级为真表格）
    leftover = [_flat(b) for b in blocks if b["type"] == "paragraph" and _flat(b).startswith("|")]
    check(not leftover, "表格不再退化成带竖线的段落", leftover)
    tables = [b for b in blocks if b["type"] == "table"]
    check(len(tables) == 1, "Markdown 表格 → 一个 Notion table 块", len(tables))
    tb = tables[0]["table"]
    check(tb["has_column_header"] is True, "首行识别为表头")
    cells = [[(c[0]["text"]["content"] if c else "") for c in r["table_row"]["cells"]]
             for r in tb["children"]]
    check(all(len(r) == tb["table_width"] for r in cells),
          "每行单元格数补齐到 table_width（缺列补空，否则 API 整块拒收）", cells)
    check("|" not in "".join("".join(r) for r in cells), "单元格里不残留竖线", cells)
    check(len(cells) == 2 and cells[0] == ["维度", "分数"] and cells[1] == ["传播度", "8"],
          "分隔行 |---|---| 被丢弃，表头与数据行都保留", cells)


def test_callouts():
    _, blocks = nu.parse_markdown(MD)
    callouts = [b for b in blocks if b["type"] == "callout"]
    icons = [b["callout"]["icon"]["emoji"] for b in callouts]
    check(icons == ["📍", "💡", "🔍"],
          "📍 路线条 / 💡 说人话 / 🔍 名词解释灰框 → 三个 callout block", icons)
    check(all(b["callout"]["color"] == "gray_background" for b in callouts),
          "callout 统一灰底，与正文拉开层级")
    check("继续写在下一行的路线说明" in _flat(callouts[0]),
          "callout 的换行续写并进同一块，不被拆成孤立段落", _flat(callouts[0]))
    check(not _flat(callouts[2]).startswith(">"),
          "`> 🔍 …` 的灰框写法也认，且不残留引用符号", _flat(callouts[2]))


def test_length_guard():
    _, blocks = nu.parse_markdown("开头 **" + "甲" * 2500 + "** 结尾")
    items = blocks[0]["paragraph"]["rich_text"]
    bolds = [r for r in items if r.get("annotations", {}).get("bold")]
    check(len(bolds) == 2 and all(len(r["text"]["content"]) <= 2000 for r in items)
          and "".join(r["text"]["content"] for r in bolds) == "甲" * 2500,
          "超 2000 字符按片切分，加粗跨片不丢失（旧写法会把加粗劈开）")

    _, qb = nu.parse_markdown("> " + "乙" * 4100)
    qitems = qb[0]["quote"]["rich_text"]
    check(len(qitems) == 3 and all(len(r["text"]["content"]) <= 2000 for r in qitems),
          "引用 / 标题 / 列表同受 2000 保护（原先只有段落有）")


def test_lists():
    _, blocks = nu.parse_markdown("- 甲\n- 乙\n\n1. **一号判断。** 展开\n\n2. 二号判断")
    types = [b["type"] for b in blocks]
    check(types == ["bulleted_list_item", "bulleted_list_item",
                    "numbered_list_item", "numbered_list_item"],
          "有序列表 → numbered_list_item（修复前被转成无序列表，编号丢失）", types)
    check(_flat(blocks[2]).startswith("一号判断") and "1." not in _flat(blocks[2]),
          "编号数字不重复写进正文，由 Notion 自动编号", _flat(blocks[2]))


def main():
    print("── Markdown → Notion blocks ──")
    test_block_conversion()
    test_callouts()
    test_length_guard()
    test_lists()


if __name__ == "__main__":
    main()
