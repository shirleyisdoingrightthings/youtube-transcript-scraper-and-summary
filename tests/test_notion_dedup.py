"""Notion 查重回归测试。

守的是这个 bug：TYPE_SUFFIXES 原先只认「图文精读 / 逐字稿 / 深度文章」，
演讲实录与观察稿走到 detect_type_suffix 返回 None、resolve_dedup 被整个跳过，
重传只会不断新建重复页；而 infer_other_suffix 的二元猜测还会给无后缀的旧页
贴上猜错的类型后缀。两处都是"不报错、只是悄悄出错"。
"""
from _bootstrap import check  # noqa: F401  （同时完成 sys.path 注入）

import notion_upload as nu


def test_detect_type_suffix():
    cases = [
        ("张三｜某主题 - 图文精读", ("张三｜某主题", "—图文精读")),
        ("张三｜某主题—逐字稿", ("张三｜某主题", "—逐字稿")),
        ("张三｜某主题 - 演讲实录", ("张三｜某主题", "—演讲实录")),
        ("张三｜某主题—观察稿", ("张三｜某主题", "—观察稿")),
        ("张三｜某主题 - 深度文章", ("张三｜某主题", "—深度文章")),
        ("张三｜某主题", ("张三｜某主题", None)),
        ("张三｜聊聊逐字稿这件事", ("张三｜聊聊逐字稿这件事", None)),   # 无分隔符不得误判
    ]
    for title, want in cases:
        got = nu.detect_type_suffix(title)
        check(got == want, f"detect_type_suffix({title!r}) → {want}", got)


def _run(pages, suffix):
    archived = []
    nu.find_pages_by_url = lambda url: list(pages)
    nu.archive_page = lambda pid: archived.append(pid)
    title = nu.resolve_dedup("https://youtu.be/x", "张三｜某主题", suffix)
    return title, archived


def test_resolve_dedup():
    t, a = _run([], "—图文精读")
    check((t, a) == ("张三｜某主题—图文精读", []),
          "首次上传：标题自带类型后缀、不归档任何页", (t, a))

    t, a = _run([("p1", "张三｜某主题—图文精读")], "—图文精读")
    check(a == ["p1"], "同类型重传：归档旧页（幂等重建）", a)

    t, a = _run([("p1", "张三｜某主题 - 图文精读")], "—图文精读")
    check(a == ["p1"], "旧的 ' - ' 写法也认得出是同类型", a)

    t, a = _run([("p1", "张三｜某主题—演讲实录")], "—演讲实录")
    check(a == ["p1"], "演讲实录重传照样归档（修复前完全不查重）", a)

    t, a = _run([("p1", "张三｜某主题—观察稿")], "—观察稿")
    check(a == ["p1"], "观察稿重传照样归档（修复前完全不查重）", a)

    t, a = _run([("p1", "张三｜某主题—逐字稿")], "—演讲实录")
    check((t, a) == ("张三｜某主题—演讲实录", []),
          "不同类型：不动旧页，新页用自己的后缀", (t, a))

    t, a = _run([("p1", "张三｜某主题")], "—逐字稿")
    check((t, a) == ("张三｜某主题—逐字稿", []),
          "无后缀历史页：不改名不归档（绝不猜它是哪一类）", (t, a))


def main():
    print("── Notion 查重 ──")
    test_detect_type_suffix()
    test_resolve_dedup()


if __name__ == "__main__":
    main()
