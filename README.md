# YouTube → Blog | Claude Code Cookbook

A Claude Code workflow that turns any YouTube video into a structured, publication-ready blog article — and publishes it directly to Notion.

**What it does:**
1. Fetches the video transcript via [youtube-transcript.io](https://www.youtube-transcript.io)
2. Claude generates a Chinese-language deep-dive article (6-section structure)
3. Saves the article as a local Markdown file
4. Uploads it to your Notion database with video thumbnail, metadata, and proper heading hierarchy

**Best suited for:** AI/tech talks, podcasts, interviews, conference keynotes.

---

## How it works

This is a [Claude Code](https://claude.ai/code) agentic workflow. When you open this folder in a Claude Code session and send a YouTube URL, Claude automatically runs the full pipeline — no manual steps needed.

The `CLAUDE.md` file acts as the system prompt that instructs Claude to execute each step sequentially, using tool calls to run Python scripts and write files.

---

## Setup

### 1. Prerequisites

- Python 3.11+
- [Claude Code](https://claude.ai/code) (CLI or desktop app)

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

| Variable | Where to get it |
|---|---|
| `YOUTUBE_TRANSCRIPT_API_KEY` | [youtube-transcript.io](https://www.youtube-transcript.io) → sign up → copy token (without "Basic ") |
| `NOTION_API_KEY` | [notion.so/profile/integrations](https://www.notion.so/profile/integrations) → New integration → copy secret |
| `NOTION_DATABASE_ID` | Open your Notion database → copy the 32-char ID from the URL |

> **Notion database setup:** After creating the integration, open your target database in Notion, click **Share**, and grant your integration access. The database should have these properties: `Name` (title), `URL` (url), `Type` (select), `Category` (multi-select), `Created Date` (date), `Status` (status).

### 4. Create the output folder

```bash
mkdir output
```

---

## Usage

Open this folder in a Claude Code session:

```bash
cd /path/to/this/folder
claude
```

Then simply paste any YouTube URL:

```
https://youtu.be/am_oeAoUhew
```

Claude will handle the rest — no further input needed.

---

## Output format

Each generated article follows a 6-section structure (in Chinese):

1. **Metadata** — title, host, guest, URL, date
2. **TL;DR** — 150–200 character summary
3. **核心观点** — 3–5 key insights
4. **按主题重构全文内容** — full content restructured by topic with timestamps
5. **总结与展望** — conclusions, open questions, forward-looking notes
6. **参考资源** — all resources mentioned in the video, grouped by type

Articles are saved to `output/<video-title>.md` and uploaded to Notion with:
- Video thumbnail (auto-fetched from YouTube)
- Type: 视频 / Category: 播客访谈
- Direct URL link

---

## Project structure

```
.
├── CLAUDE.md               # Claude Code system prompt (the "skill")
├── fetch_transcript.py     # Step 1: fetch YouTube transcript
├── notion_upload.py        # Step 4: upload Markdown to Notion
├── requirements.txt
├── .env.example
├── .gitignore
└── output/                 # Generated articles (git-ignored)
```

---

## Customization

**Change output language:** Edit the "输出语言与风格" section in `CLAUDE.md`.

**Change article structure:** Edit the 6-section template in `CLAUDE.md` — Claude follows it strictly.

**Skip Notion upload:** Remove Step 4 from `CLAUDE.md` and leave `NOTION_*` vars empty.

**Change Notion properties:** Edit `create_page()` in `notion_upload.py` to match your database schema.

---

## API limits

| Service | Free tier |
|---|---|
| youtube-transcript.io | 20 videos/month |
| Notion API | Unlimited (with integration) |
| Claude Code | Based on your Anthropic plan |
