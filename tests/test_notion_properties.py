"""Notion 页面属性构造与 CLI 参数规范化回归测试。

守的是两类问题：
① 脚本向 Resources Library 写入已删除的 Created Date、旧 Type（视频）或旧 Category（播客访谈）导致建页 400 或落不到对应视图；
② 非法 Category / Status 静默污染数据库枚举。
"""
from _bootstrap import check

import notion_upload as nu


def test_normalize_categories():
    check(nu.normalize_categories(None) == ["AI"], "默认 Category 为 ['AI']")
    check(nu.normalize_categories(["finance", "AI", "Finance"]) == ["Finance", "AI"],
          "Category 大小写规范化并去重保序")
    check(nu.normalize_categories(["AI, Personal", "entertainment"]) == ["AI", "Personal", "Entertainment"],
          "支持逗号分隔与多次传参混合")
    try:
        nu.normalize_categories(["播客访谈"])
    except ValueError:
        check(True, "已废弃/非法的 Category（如播客访谈）会显式报错拦截")
    else:
        raise AssertionError("非法 Category 应当抛 ValueError")


def test_normalize_status():
    check(nu.normalize_status(None) == "To Do", "默认 Status 为 'To Do'")
    check(nu.normalize_status("in progress") == "In Progress", "Status 规范化为 'In Progress'")
    check(nu.normalize_status("Complete") == "Complete", "Status 支持 'Complete'")
    try:
        nu.normalize_status("Not started")
    except ValueError:
        check(True, "旧 Status（Not started）会显式报错拦截")
    else:
        raise AssertionError("非法 Status 应当抛 ValueError")


def test_build_page_properties():
    props = nu.build_page_properties(
        "测试标题—图文精读",
        "https://youtu.be/dQw4w9WgXcQ",
        categories=["AI", "Finance"],
        status="In Progress",
        description="30 秒速览测试。",
    )
    check("Created Date" not in props, "不再写入已删除的 Created Date（Created Time 由 Notion 自动生成）", props)
    check(props["Type"] == {"select": {"name": "🎬 YouTube"}}, "Type 固定写为 '🎬 YouTube'", props["Type"])
    check(props["Category"] == {"multi_select": [{"name": "AI"}, {"name": "Finance"}]},
          "Category 支持多选 AI / Finance / Personal / Entertainment", props["Category"])
    check(props["Status"] == {"status": {"name": "In Progress"}}, "Status 支持 'In Progress'", props["Status"])
    check(props["Description"] == {"rich_text": [{"type": "text", "text": {"content": "30 秒速览测试。"}}]},
          "传入 description 时写入 Description", props.get("Description"))

    props_min = nu.build_page_properties("默认页", "https://youtu.be/abc")
    check("Description" not in props_min, "无 description 时省略 Description 字段")
    check(props_min["Status"] == {"status": {"name": "To Do"}}, "默认 Status 为 'To Do'")


def test_extract_description():
    md = (
        "# 标题\n\n"
        "> 从多 Agent 协作到 [思维链监控](https://example.com)，**Noam Brown** 谈能力跃迁与安全边界。\n\n"
        "👩 编译：Shirley\n\n"
        "## 核心看点\n"
    )
    got = nu.extract_description(md)
    check(got == "从多 Agent 协作到 思维链监控，Noam Brown 谈能力跃迁与安全边界。",
          "自动提取开头题记 blockquote 并去掉链接/加粗标记", got)

    md_callout_only = "# 标题\n\n> 💡 嘉宾背景：某研究员。\n\n正文段落。\n"
    check(nu.extract_description(md_callout_only) == "",
          "仅有 callout（💡/📍/🔍）时不误抽为题记")


def test_parse_args():
    args = nu.parse_args([
        "article.md",
        "https://youtu.be/xyz",
        "--category", "Finance,Personal",
        "--status", "In Progress",
        "--description", "自定义速览",
    ])
    check(args.markdown_file == "article.md" and args.youtube_url == "https://youtu.be/xyz",
          "parse_args 解析位置参数")
    check(nu.normalize_categories(args.categories) == ["Finance", "Personal"],
          "parse_args 解析 --category")
    check(nu.normalize_status(args.status) == "In Progress" and args.description == "自定义速览",
          "parse_args 解析 --status 与 --description")


def main():
    print("── Notion 属性与参数 ──")
    test_normalize_categories()
    test_normalize_status()
    test_build_page_properties()
    test_extract_description()
    test_parse_args()


if __name__ == "__main__":
    main()
