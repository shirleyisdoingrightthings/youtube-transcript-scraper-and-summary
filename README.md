# YouTube → Blog | Claude Code Cookbook

这是一个基于 Claude Code 的自动化工作流，能够将任意 YouTube 视频转换为结构化、可直接发布的博客文章，并自动上传到 Notion。

**功能亮点：**
1. 通过 [youtube-transcript.io](https://www.youtube-transcript.io) 抓取视频字幕
2. Claude 自动生成中文深度解读文章（标准 6 段式结构）
3. 将文章保存为本地 Markdown 文件
4. 自动上传到 Notion 数据库，并包含视频封面图、元数据及正确的标题层级

**适用场景：** AI/科技讲座、播客、深度访谈、行业大会主题演讲。

---

## 工作原理

这是一个 [Claude Code](https://claude.ai/code) Agentic 工作流。当你在 Claude Code 会话中打开此文件夹并发送一个 YouTube 链接时，Claude 会自动运行整套流水线——无需任何人工干预。

`CLAUDE.md` 文件作为系统级 Prompt，指示 Claude 按顺序执行每个步骤，包括通过工具调用来运行 Python 脚本和写入文件。符合 Harness Engineering 的 Progressive Disclosure（渐进式信息披露）原则，具体写作规范通过 `skills/` 按需加载。

---

## 环境配置

### 1. 前置要求

- Python 3.11+
- [Claude Code](https://claude.ai/code)（CLI 命令行或桌面应用）

### 2. 安装依赖项

```bash
pip install -r requirements.txt
```

### 3. 配置 API Keys

```bash
cp .env.example .env
```

编辑 `.env` 文件并填入你的凭证：

| 变量 | 获取方式 |
|---|---|
| `YOUTUBE_TRANSCRIPT_API_KEY` | [youtube-transcript.io](https://www.youtube-transcript.io) → 注册 → 复制 token（不含 "Basic "）|
| `NOTION_API_KEY` | [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → New integration → 复制 secret |
| `NOTION_DATABASE_ID` | 在 Notion 中打开你的目标数据库 → 从 URL 中复制 32 位 ID |

> **Notion 数据库设置：** 创建 Integration 后，在 Notion 中打开目标数据库，点击 **Share（分享）**，并赋予你的 Integration 访问权限。该数据库需要包含以下属性：`Name` (Title), `URL` (URL), `Type` (Select), `Category` (Multi-select), `Created Date` (Date), `Status` (Status)。

### 4. 创建输出目录

```bash
mkdir output
```

---

## 使用方法

在 Claude Code 会话中打开此文件夹：

```bash
cd /path/to/this/folder
claude
```

然后只需粘贴任意 YouTube 链接：

```
https://youtu.be/am_oeAoUhew
```

Claude 将会自动处理接下来的所有步骤——无需提供额外的指令。

---

## 输出格式

生成的每篇文章都遵循严格的 6 段式结构（简体中文）：

1. **Metadata（元数据）** — 标题、主持人、嘉宾、链接、日期
2. **TL;DR** — 150–200 字的核心摘要
3. **核心观点** — 3–5 个最有价值的洞见
4. **按主题重构全文内容** — 打破原有时间线，按主题重组并附带时间戳
5. **总结与展望** — 结论、开放性问题、前瞻性预测
6. **参考资源** — 视频中提及的所有资源（模型、论文、工具等），分类整理

文章将被保存至 `output/<视频标题>.md`，并自动上传至 Notion，包含：
- 视频封面图（自动从 YouTube 抓取）
- Type: 视频 / Category: 播客访谈
- 直接链接到视频的 URL 字段

---

## 项目结构

```
.
├── CLAUDE.md               # Claude Code 系统 Prompt（Agent 的大脑）
├── fetch_transcript.py     # Step 1: 抓取 YouTube 字幕
├── notion_upload.py        # Step 4: 将 Markdown 上传至 Notion
├── requirements.txt
├── .env.example
├── .gitignore
├── skills/
│   └── article_generation.md # 按需加载的文章生成规范（Harness Engineering）
└── output/                 # 生成的文章目录（被 Git 忽略）
```

---

## 自定义修改

**更改输出语言：** 编辑 `skills/article_generation.md` 中的「输出语言与风格」部分。

**更改文章结构：** 编辑 `skills/article_generation.md` 中的 6 段式模板——Claude 会严格遵守。

**跳过 Notion 上传：** 从 `CLAUDE.md` 中删除 Step 4，并保留 `NOTION_*` 环境变量为空。

**修改 Notion 属性：** 修改 `notion_upload.py` 中的 `create_page()` 函数，使其与你自己的数据库结构相匹配。

---

## API 限制

| 服务 | 免费额度 |
|---|---|
| youtube-transcript.io | 20 个视频 / 月 |
| Notion API | 无限制（配合 Integration 使用） |
| Claude Code | 基于你的 Anthropic 订阅计划计算 |
