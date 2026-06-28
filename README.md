# YouTube → Blog | Claude Code 自动化工作流

将任意 YouTube 视频链接转换为可直接发布的中文**图文精读稿**或**对话体逐字稿**，并自动归档至 Notion。适用于 AI/科技讲座、播客访谈、行业大会演讲等内容类型。

> **环境配置与使用指南** → [PLAYBOOK.md](PLAYBOOK.md)

<details>
<summary>📄 查看完整 Blog 预览图</summary>

![Blog 输出预览](full_demo.png)

</details>

---

## 工作流

在 Claude Code 中打开此目录，发送 YouTube 链接，工作流自动执行以下步骤：

1. **抓取字幕** — 调用 [youtube-transcript.io](https://www.youtube-transcript.io) API 获取带时间戳的完整字幕，同时保存为本地 `transcript.json`
2. **意图路由与生成** — 根据用户输入（默认生成**图文精读稿**；含"逐字稿/对话体"等关键词时生成**对话体逐字稿**），调用 `skills/illustrated_deepdive.md` 或 `skills/dialogue_transcript.md` 中的规范，生成对应的 Markdown 输出
3. **对照字幕核校** — 生成后、归档前，逐板块对照 `transcript.json` 核对事实/数字/专名/因果，对照 `glossary.md` 统一术语，区分必改硬伤与可选润色（工作流核心步骤，两种产物通用）
4. **归档文件** — 按系统自动生成的中文标题建立子目录，保存对应的 Markdown 文件（如 `<标题> - 图文精读.md` 或 `<标题> - 逐字稿.md`）与原始字幕数据
5. **同步 Notion** — 上传文章内容（含封面图、元数据），已有页面自动归档旧版本后重建（幂等）

---

## 文件结构

```text
.
├── CLAUDE.md                   # 系统 Prompt，控制 Agent 执行逻辑
├── glossary.md                 # 项目术语对照表（核校时统一译法与写法）
├── fetch_transcript.py         # 字幕抓取脚本（支持 --output 参数）
├── notion_upload.py            # Notion 上传脚本（幂等 upsert）
├── tags.json                   # 标签字典（约束分类标签与双链术语的边界）
├── skills/
│   ├── illustrated_deepdive.md # 图文精读稿生成规范（默认产物）
│   └── dialogue_transcript.md  # 对话体逐字稿生成规范
├── logs/
│   ├── workflow_execution.md   # 每次执行记录
│   └── system_changelog.md    # 系统架构变更日志
├── output/
│   └── <生成的中文标题>/
│       ├── <生成的中文标题> - 图文精读.md
│       ├── <生成的中文标题> - 逐字稿.md
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
| 技能层 | `skills/` | 存放按需加载的专项规范（图文精读 / 逐字稿），与控制层解耦 |
| 数据层 | `tags.json`、`glossary.md` | 标签收敛防发散；术语对照表保证跨篇译法统一 |
| 执行层 | `*.py` | 各步骤对应的独立脚本，可单独调用 |
| 观测层 | `logs/` | 执行日志与系统变更记录，本地保留不进 Git |
| 输出层 | `output/` | 按视频标题归档的 Markdown 文章与字幕原文 |
