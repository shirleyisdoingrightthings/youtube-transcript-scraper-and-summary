"""本地图片 → Notion File Upload 的回归测试。

守的是两类"不报错、只是悄悄出错"：
① 正文里的本地图片被静默降级成占位文字，发出去的文章没有图；
② 解析阶段的内部占位块漏到请求里——那种块 Notion 不认，整批 95 个块会一起 400，
   而报错信息只会说"validation error"，很难定位到是哪张图。
"""
import os
import tempfile

from _bootstrap import check

import notion_upload as nu


def _blocks(md: str):
    return nu.parse_markdown(md)[1]


def run():
    # ── 解析：外链仍走 external，本地路径留占位块 ──
    b = _blocks("![封面](https://example.com/a.png)")
    check(b[0]["image"]["type"] == "external", "http(s) 外链仍走 external image block")

    b = _blocks("![图 1 · 机制图](figs/f1.png)")
    check(nu.is_local_image(b[0]), "本地路径留成内部占位块，不再直接降级成文字")
    check(b[0]["image"][nu.LOCAL_IMAGE_TYPE]["alt"] == "图 1 · 机制图",
          "占位块带上 alt，降级时才有话可写")

    # ── 解析后：真文件走上传，拿 file_upload id ──
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "figs"), exist_ok=True)
        png = os.path.join(d, "figs", "f1.png")
        with open(png, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)

        calls = []

        def fake_upload(path):
            calls.append(path)
            return "upload-id-123"

        out = nu.resolve_local_images(_blocks("![图 1](figs/f1.png)"), d, uploader=fake_upload)
        check(out[0]["image"]["type"] == "file_upload", "本地图片换成 file_upload 引用")
        check(out[0]["image"]["file_upload"]["id"] == "upload-id-123", "引用的是上传返回的 id")
        check(len(calls) == 1, "上传被调用一次", calls)

        # 同一张图在正文里出现两次，只应上传一次（这里靠调用方缓存，函数级不缓存）
        two = _blocks("![图 1](figs/f1.png)\n\n![图 1 再次引用](figs/f1.png)")
        out = nu.resolve_local_images(two, d, uploader=fake_upload)
        check(all(x["image"]["type"] == "file_upload" for x in out if x["type"] == "image"),
              "同一张图多处引用都能换成 file_upload")

        # ── 文件不存在：降级成占位文字，绝不把内部占位块发出去 ──
        out = nu.resolve_local_images(_blocks("![图 9 · 还没画](figs/f9.png)"), d,
                                      uploader=fake_upload)
        check(out[0]["type"] == "paragraph", "文件不存在时降级成段落")
        check("图 9 · 还没画" in out[0]["paragraph"]["rich_text"][0]["text"]["content"],
              "降级文字里带上 alt，读者知道缺的是哪张")

        # ── 上传失败：同样降级，不炸整篇 ──
        def boom(_path):
            raise RuntimeError("网络炸了")

        out = nu.resolve_local_images(_blocks("![图 1](figs/f1.png)"), d, uploader=boom)
        check(out[0]["type"] == "paragraph", "上传失败时降级成段落，不中断整篇上传")

        # ── 兜底：处理完不许再有内部占位块 ──
        mixed = _blocks("![a](figs/f1.png)\n\n正文一段\n\n![b](figs/nope.png)")
        out = nu.resolve_local_images(mixed, d, uploader=fake_upload)
        check(not any(nu.is_local_image(x) for x in out),
              "处理完没有内部占位块残留（残留会让整批 95 个块一起 400）")

    # ── 版本号：带 file_upload 的批次必须用新版本号发 ──
    check(nu.has_uploaded_image([nu.uploaded_image_block("x")]), "识别出批次里有 file_upload 块")
    check(not nu.has_uploaded_image([nu.image_block("https://e.com/a.png")]),
          "纯外链批次不触发版本号切换")
    check(nu.UPLOAD_HEADERS["Notion-Version"] != nu.HEADERS["Notion-Version"],
          "上传用的版本号与查重 / 建页用的不是同一个")


main = run   # run_all.py 调的是 main()


if __name__ == "__main__":
    run()
