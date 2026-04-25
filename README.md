# YouTube → Blog | Claude Code 自动化工作流

将任意 YouTube 视频链接转换为结构化中文深度解读文章，并自动归档至 Notion 与 Obsidian。适用于 AI/科技讲座、播客访谈、行业大会演讲等内容类型。

> **环境配置与使用指南** → [PLAYBOOK.md](PLAYBOOK.md)

<details>
<summary>📄 查看完整 Blog 预览图</summary>

![Blog 输出预览](full_demo.png)

</details>

---

## 工作流

在 Claude Code 中打开此目录，发送 YouTube 链接，工作流自动执行以下步骤：

1. **抓取字幕** — 调用 [youtube-transcript.io](https://www.youtube-transcript.io) API 获取带时间戳的完整字幕，同时保存为本地 `transcript.json`
2. **生成文章** — 按照 `skills/article_generation.md` 中的规范，生成 6 段式中文深度解读（Metadata → TL;DR → 核心观点 → 按主题重构 → 总结与展望 → 参考资源）
3. **归档文件** — 按视频完整标题建立子目录，保存 Markdown 文章与字幕文件
4. **同步 Notion** — 上传文章内容（含封面图、元数据），已有页面自动归档旧版本后重建（幂等）
5. **同步 Obsidian** — 将带 YAML frontmatter 标签的 Markdown 复制到 Second Brain 目录

---

## 文件结构

```text
.
├── CLAUDE.md                   # 系统 Prompt，控制 Agent 执行逻辑
├── fetch_transcript.py         # 字幕抓取脚本（支持 --output 参数）
├── notion_upload.py            # Notion 上传脚本（幂等 upsert）
├── tags.json                   # 标签字典（约束分类标签与双链术语的边界）
├── skills/
│   └── article_generation.md  # 文章生成规范（按需加载）
├── logs/
│   ├── workflow_execution.md   # 每次执行记录
│   └── system_changelog.md    # 系统架构变更日志
├── output/
│   └── <视频完整标题>/
│       ├── <视频完整标题>.md
│       └── transcript.json
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 系统架构

| 层级 | 文件 | 职责 |
|---|---|---|
| 控制层 | `CLAUDE.md` | 定义执行步骤与异常处理规则，是 Agent 的唯一入口 |
| 技能层 | `skills/` | 存放按需加载的专项规范，与控制层解耦 |
| 数据层 | `tags.json` | 强约束标签收敛，防止知识库发散 |
| 执行层 | `*.py` | 各步骤对应的独立脚本，可单独调用 |
| 观测层 | `logs/` | 执行日志与系统变更记录，本地保留不进 Git |
| 输出层 | `output/` | 按视频标题归档的 Markdown 文章与字幕原文 |
