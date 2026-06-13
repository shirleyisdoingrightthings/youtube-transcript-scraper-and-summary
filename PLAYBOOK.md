# YouTube → Blog | 操作手册 (PLAYBOOK)

> 本文档为实操指南，说明如何配置、运行以及自定义你的 YouTube 抓取与总结工作流。
> 系统架构及设计思想说明见 → [README.md](README.md)

---

## 一、环境配置 (Setup)

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

## 二、使用方法 (Usage)

在 Claude Code 会话中打开此文件夹：

```bash
cd "/Users/jialiwu/Desktop/youtube transcript scraper and summary"
claude
```

然后只需粘贴任意 YouTube 链接。默认生成**图文精读稿**（可直接发公众号，含标题/摘要/封面 Prompt/嘉宾背景/核心观点/重构正文）；若想要**对话体逐字稿**，在输入时带上"逐字稿/对话体"等关键词即可：

```
# 默认 —— 生成图文精读稿
帮我把这个视频做成图文精读：https://youtu.be/am_oeAoUhew

# 指定 —— 整理为对话体逐字稿
帮我将这个视频整理为对话体逐字稿：https://youtu.be/am_oeAoUhew
```

Claude 将会自动识别意图调用对应技能，并处理接下来的所有步骤（字幕抓取、生成排版、**对照字幕核校**、本地归档、Notion / Obsidian 同步）——无需提供额外的干预。

---

## 三、自定义修改 (Customization)

工作流的高度解耦设计允许你轻松进行客制化：

- **更改输出语言：** 编辑 `skills/illustrated_deepdive.md` 或 `skills/dialogue_transcript.md` 中的「输出语言」规则。
- **更改文章结构：** 编辑 `skills/illustrated_deepdive.md` 中的 9 段式结构，或调整 `dialogue_transcript.md` 中的格式要求。
- **统一术语译法：** 在 `glossary.md` 中增改术语对照，核校（Step 2.5）时会据此统一全篇及系列上下集。
- **跳过 Notion 上传：** 从主控台 `CLAUDE.md` 中删除 Step 4，并保留 `.env` 中的 `NOTION_*` 环境变量为空。
- **修改 Notion 映射属性：** 修改 `notion_upload.py` 中的 `create_page()` 函数，使其与你自己的数据库结构字段严格匹配。

---

## 四、API 限制说明

遇到调用失败时，请优先检查以下额度是否耗尽：

| 服务 | 免费额度 / 计费 |
|---|---|
| youtube-transcript.io | 20 个视频 / 月（免费版） |
| Notion API | 无限制（配合 Integration 使用） |
| Claude Code | 基于你的 Anthropic 订阅计划产生 Token 费用 |
