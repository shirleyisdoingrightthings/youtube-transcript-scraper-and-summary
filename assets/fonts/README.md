# 手绘图字体

配图统一用**方案 A**：拉丁与数字用 Architects Daughter（Excalidraw 的 Virgil 在 Google Fonts 上的近似替代），中文用霞鹜文楷 Lite。理由见 `skills/diagram_style.md`。

| 文件 | 用途 | 许可 | 进版本库 |
|---|---|---|---|
| `ArchitectsDaughter-Regular.woff2` | 拉丁 / 数字 | OFL | ✅ 28 KB |
| `LXGWWenKaiLite-Regular.ttf` | 中文 | OFL | ❌ 13 MB，见下 |

## 中文字体怎么来

13 MB 的全量 TTF 不进 Git（`.gitignore` 已排除）。丢了就重下：

```bash
curl -sL -o assets/fonts/LXGWWenKaiLite-Regular.ttf \
  https://github.com/lxgw/LxgwWenKai-Lite/releases/download/v1.522/LXGWWenKaiLite-Regular.ttf
```

## 为什么要子集化后内联，而不是挂 CDN

两个硬约束：Artifact 的 CSP **只允许 fonts.gstatic.com 提供字体文件**，自带字体只能走 data URI；而不内联就得赌读者本机装了中文字体，同一张图换台电脑换一副面孔，导成图片时服务器上更是直接没有。

裁完通常只有几十到几百 KB（两篇成品全部 1205 个汉字 → 270 KB）。

## 用法

首次准备环境：

```bash
python3 -m venv assets/fonts/.venv && assets/fonts/.venv/bin/pip install fonttools brotli
```

按实际用字裁字体并打印可直接粘进页面的 `@font-face`：

```bash
python3 assets/fonts/subset_font.py --text-from "output/<标题>/<成品>.md" --out /tmp/wenkai.woff2 --css
```
