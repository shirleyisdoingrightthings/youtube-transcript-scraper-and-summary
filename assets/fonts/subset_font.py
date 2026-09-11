#!/usr/bin/env python3
"""把手绘图要用的字体按实际用字裁成小文件，并输出可直接内联的 @font-face。

为什么要子集化：霞鹜文楷全量 13 MB，整包内联进页面不现实；但一张图真正用到的
汉字通常只有几百个，裁完是几十到几百 KB。内联而不是走 CDN，是因为 Artifact 的
CSP 只允许 fonts.gstatic.com 提供字体文件，自带字体只能走 data URI；更要紧的是
不内联就得靠读者本机有中文字体，同一张图换台电脑就换一副面孔。

依赖 fonttools + brotli，不在系统 Python 里装，用同目录的虚拟环境：
    python3 -m venv assets/fonts/.venv
    assets/fonts/.venv/bin/pip install fonttools brotli

用法：
    # 从若干文件里收集用字，裁出 woff2 并打印 @font-face
    python3 assets/fonts/subset_font.py --text-from a.md b.md --out /tmp/wenkai.woff2 --css

    # 直接给一段文字
    python3 assets/fonts/subset_font.py --text "内存带宽受限 权重 KV cache" --out /tmp/x.woff2
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FONT = os.path.join(HERE, "LXGWWenKaiLite-Regular.ttf")
VENV_PY = os.path.join(HERE, ".venv", "bin", "python")

# 标点与全角符号：图上一定会用到，永远带上，免得裁完出现豆腐块
ALWAYS = set("　，。、；：？！“”‘’（）《》〈〉【】「」〔〕…—～·％℃±×÷＝≈≤≥→←↑↓／　")
ALWAYS |= {chr(c) for c in range(32, 127)}


def collect(texts: list[str], files: list[str]) -> str:
    buf = "".join(texts)
    for f in files:
        with open(f, encoding="utf-8") as fh:
            buf += fh.read()
    chars = set(re.findall(r"[一-鿿㐀-䶿]", buf)) | ALWAYS
    return "".join(sorted(chars))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", default=DEFAULT_FONT)
    ap.add_argument("--text", action="append", default=[])
    ap.add_argument("--text-from", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    ap.add_argument("--family", default="WenKai")
    ap.add_argument("--css", action="store_true", help="额外打印内联 @font-face")
    a = ap.parse_args()

    if not os.path.exists(a.font):
        print(f"[ERROR] 找不到字体：{a.font}", file=sys.stderr)
        return 1
    py = VENV_PY if os.path.exists(VENV_PY) else sys.executable
    subset = [py, "-m", "fontTools.subset"]

    text = collect(a.text, a.text_from)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
        tf.write(text)
        txt_path = tf.name
    try:
        cmd = subset + [a.font, f"--text-file={txt_path}", "--flavor=woff2",
                        "--layout-features=", f"--output-file={a.out}"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("[ERROR] 子集化失败，多半是虚拟环境没建或缺 brotli：", file=sys.stderr)
            print(r.stderr.strip()[:800], file=sys.stderr)
            return 1
    finally:
        os.unlink(txt_path)

    size = os.path.getsize(a.out)
    cjk = len([c for c in text if "一" <= c <= "鿿"])
    print(f"✔ {a.out}　{size // 1024} KB　收字 {cjk} 个汉字（内联后约 {size * 4 // 3 // 1024} KB）")

    if a.css:
        b64 = base64.b64encode(open(a.out, "rb").read()).decode()
        print(f'@font-face{{font-family:"{a.family}";'
              f'src:url(data:font/woff2;base64,{b64}) format("woff2");font-display:swap}}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
