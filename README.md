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

0. **播客雷达（可选，手动触发）** — 说「跑雷达」即扫描 20 个 AI 播客频道最近一周/半月的新片，按**相对热度**（本片播放 ÷ 该频道自身基线，跨频道可比）出榜单并给三档编辑筛选；零 API key、零配额（走频道 RSS）
1. **选题预判** — 先抓字幕略读、四维加权打分，给出"值不值得做"的编辑结论后停住等指令（预判用 `--prefer-free`，不消耗付费源配额）
2. **抓取字幕** — 调用 [youtube-transcript.io](https://www.youtube-transcript.io) API 获取带时间戳的完整字幕，并做覆盖率校验（不足 90% 自动换源重抓，两源皆残缺则硬失败），保存为本地 `transcript.json`
3. **意图路由与生成** — 根据用户输入（默认生成**图文精读稿**；含"逐字稿/对话体"等关键词时生成**对话体逐字稿**；单人演讲走**演讲实录**；多信源行业判断走**观察稿**），调用 `skills/` 下对应规范生成 Markdown 输出
4. **对照字幕核校 + Agent Council 自检** — 生成后、归档前，逐板块对照 `transcript.json` 核对事实/数字/专名/因果，对照 `glossary.md` 统一术语；再由激进 + 保守两位全新审稿人并行打分、全新 Judge 裁决冲突，清掉硬伤
5. **归档三件套** — 按系统生成的中文标题建立子目录，保存成品 Markdown、原始字幕与交接文档
6. **同步 Notion** — 上传文章内容（含封面图、元数据），同类型页面自动归档旧版本后重建（幂等）

---

## 文件结构

```text
.
├── CLAUDE.md                       # 系统 Prompt，控制 Agent 执行逻辑
├── AGENTS.md                       # → CLAUDE.md 的符号链接（两个入口永不漂移）
├── PLAYBOOK.md                     # 操作手册：配置、使用、全流程与自定义
├── glossary.md                     # 项目术语对照表（核校时统一译法与写法）
├── radar.py                        # 播客雷达：监控频道 RSS，按相对热度出候选榜单（手动触发）
├── radar_channels.json             # 雷达的频道白名单 + 嘉宾名单
├── fetch_transcript.py             # 字幕抓取（--output / --prefer-free，内置覆盖率校验）
├── notion_upload.py                # Notion 上传脚本（按类型后缀查重，幂等 upsert）
├── notion_read.py                  # 读回线上稿（精修时对照用）
├── check_transcript_edit.py        # 精编稿体检：时间戳逆序 + 时间轴缺口扫描
├── http_utils.py                   # 三个脚本共用的 HTTP 退避重试
├── skills/
│   ├── topic_assessment.md         # 阶段 -1 选题预判规范（四维加权打分）
│   ├── illustrated_deepdive.md     # 图文精读稿生成规范（默认产物）
│   ├── dialogue_transcript.md      # 对话体逐字稿 / 演讲实录生成规范
│   ├── observation_commentary.md   # 观察 / 观点稿生成规范（多信源）
│   ├── reader_facing_review.md     # 复核清单 + Agent Council 三角色协议
│   ├── council/                    # Council 三角色 prompt 模板（progressive / conservative / judge）
│   ├── handoff_doc.md              # 交接文档模板与更新铁律
│   ├── transcript_files.md         # 批量预判的字幕命名、pending 存放与 summary 导读
│   ├── proper_noun_check.md        # Step 2.5 专名核对铁律（五条判据）
│   ├── notion_publish.md           # Step 4 上传细则（查重、图片、人工处理项）
│   └── meta_harness.md             # Step 5.5 棘轮检查 + Step 6 系统自检
├── tests/                          # 回归测试（python3 tests/run_all.py）
├── docs/
│   └── workflow.svg                # 工作流设计视图
├── logs/
│   ├── workflow_execution.md       # 每次执行记录
│   └── system_changelog.md         # 系统架构变更日志
├── transcripts_pending/            # 预判后暂缓的字幕 + 同名 .summary.md 导读（不进 Git，重抓要花钱）
├── radar_data/                     # 雷达的 SQLite 时间序列与历史榜单（不进 Git，可重建）
├── output/
│   └── <生成的中文标题>/
│       ├── <生成的中文标题> - 图文精读.md
│       ├── <生成的中文标题> - 逐字稿.md
│       ├── 交接文档.md
│       └── transcript.json
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## 系统架构

| 层级 | 文件 | 职责 |
|---|---|---|
| 控制层 | `CLAUDE.md`（`AGENTS.md` 为其符号链接）| 定义执行步骤与异常处理规则，是 Agent 的唯一入口 |
| 技能层 | `skills/` | 存放按需加载的专项规范（选题预判 / 四种文体 / 复核 / 交接），与控制层解耦 |
| 数据层 | `glossary.md` | 术语对照表，保证跨篇、跨系列上下集的译法与写法统一 |
| 执行层 | `*.py` | 各步骤对应的独立脚本，可单独调用；网络请求统一走 `http_utils` 的退避重试 |
| 测试层 | `tests/` | 回归测试，钉住那些「不报错、只是悄悄出错」的老 bug |
| 观测层 | `logs/` | 执行日志与系统变更记录（随仓库版本化，是这套流程的演进史）|
| 输出层 | `output/` | 按视频标题归档的 Markdown 文章与字幕原文 |
