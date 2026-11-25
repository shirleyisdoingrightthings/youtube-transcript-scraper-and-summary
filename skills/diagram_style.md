# 配图与图解规范（Diagram Style · 基于 diagram-design 技能）

> **唯一绘图引擎**：本工作流涉及的全部架构图、流程图、机制图与数据图表，**统一按已安装的 `diagram-design` 技能执行**（全局路径 `~/.gemini/config/skills/diagram-design/SKILL.md`）。不再维护独立的 `rough.js` 手绘管线。
> **忠实度底线**：图是正文的一部分，受同一条忠实度红线约束——**图上每个数字、专名与器件结构必须先核到一手出处再画，没核实的不画；出处本身不进图，统一写入正文或图注。**

---

## 一、先判断该不该画（减法优先）

1. **只有当图比一段好文字或一张三列表格更快讲清机制/拓扑/对比时才画**；单纯列清单用表格或无序列表。
2. **列分镜再动笔**：一篇稿子先列出 2–6 张图的分镜表（主题 / 核心判断 / 选定的 `diagram-design` 视觉类型 / 关键标签），经确认后再逐张生成，避免返工。
3. **目标信息密度 4/10**：单图严格守住 `diagram-design` 复杂度预算（**≤9 个节点、≤12 条连线、≤2 个焦点高亮元素、≤3 个平铺分区**）；超出就拆成「总览图 + 细节图」。

---

## 二、标准执行流程（严格遵循 `diagram-design`）

每次为稿件或项目文档配图时，按以下顺序执行：

1. **加载主技能与类型规范**：
   - 先读取 `~/.gemini/config/skills/diagram-design/SKILL.md`；
   - 若行为、状态或门禁承载核心语义，先读取 `references/semantic-patterns.md` 选定语义模式，再从 52 种视觉类型（Architecture / Process / Data flow / Flowchart / Sequence / Quadrant / Layer stack / Bar / Line / Scatter 等）中选出最匹配的类型并**必读对应的 `references/type-*.md`**。
2. **遵守设计系统与中文排版合同**（见 `diagram-design/references/style-guide.md`）：
   - 保持克制的编辑风配色体系（默认冷暖中性纸底 `#f5f5f5`、深墨 `#2d3142`、蓝灰 `#4f5d75`、单焦点暖橙 `#bf4520` 最多用于 1–2 个核心节点、外链/API 蓝 `#2e5aa8`），严禁暗黑霓虹渐变、严禁 `box-shadow`、严禁把所有节点涂成高亮色。
   - **中文标签铁律**：字号下限 **12px**（不压小字号，放不下就精简标签）；按字符宽度预算（全角汉字/标点 `1em`，西文 `0.60em` sans / `0.62em` mono）预留充足留白并向上取整到 **4px 栅格**；技术副标签（脚本名、协议、端口、URL）保持西文等宽字体。
   - **六条连接器硬规则**：全正交圆角折线（`r=8`，严禁斜线）、标签与连线保留 6–10px 间距并配不透明纸底遮罩、零重叠、同边多线分散锚点、不穿越非端点方框、先画连线后画节点。
   - **无障碍 SVG 契约**：`<svg role="img" aria-labelledby="<slug>-title <slug>-desc">`，`<title>` 为首个子元素，图例置于底部独立横向条带。
3. **生成单文件 HTML 源稿并跑双门禁**：
   在 `diagram-design` 技能目录下对生成的 `.html` 执行自动化校验，**未全绿禁止导出**：
   ```bash
   python3 ~/.gemini/config/skills/diagram-design/scripts/self_check.py <diagram.html>
   python3 ~/.gemini/config/skills/diagram-design/scripts/verify_geometry.py <diagram.html>
   ```
   （离线或用于 GitHub README 内嵌的静态图加 `--offline`。）
4. **导出静态产物嵌入正文**：
   - 导出独立 `.svg`（供网页、文档或 GitHub README）：
     ```bash
     python3 ~/.gemini/config/skills/diagram-design/scripts/export_svg.py <diagram.html> <out.svg> --system-fonts
     ```
   - 导出高清 `.png`（2× 倍率，供公众号与 Notion 直传）：
     ```bash
     python3 ~/.gemini/config/skills/diagram-design/scripts/export_png.py <diagram.html> <out.png> 2
     ```
   - 正文引用格式：`![图 1 · <这张图在解释什么>](figs/f1.png)`（`notion_upload.py` 会自动通过 Notion File Upload API 托管同目录下的本地图片）。

---

## 三、数字、专名与图表忠实度红线

1. **先核对再上图**：厂商规格以一手官方文档为准（优先使用 Exa MCP 核查原文），不把嘉宾口头约数直接当硬件规格；官方已有清晰数据原图时直接引用原图并配图注（指标定义、日期、来源），不重画。
2. **出处不进图**：时间戳、页码、文档名一律放正文或图注，保持画面干净。
3. **图元映射真实值**：数据类图表（柱状、折线、散点、瀑布、热力等）严格按真实数值比例绘制，不截断 Y 轴误导观感；示意性图形必须注明为示意。
4. **视觉终检**：导出后须确认零文字截断、零元素重叠、对比度达标（正文 ≥4.5:1，图形 ≥3:1）且在窄屏容器中不撑破页面布局。
