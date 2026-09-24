# YouTube → Blog | 操作手册 (PLAYBOOK)

> 本文档为实操指南，说明如何配置、运行、读懂以及自定义你的 YouTube 抓取与总结工作流。
> 系统架构及设计思想说明见 → [README.md](README.md)；逐条指令逻辑见 → [CLAUDE.md](CLAUDE.md)。
>
> ⚠️ **本工作流持续迭代中，本文档非最终版**。每次对流程/脚本/规范做永久性改动后，都应回来同步这里（见 CLAUDE.md Step 6 Meta-Harness）。

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

### 5.（可选）少点几次"允许"

`.claude/settings.local.json` 里预置了权限白名单：本项目的四个脚本、只读 git 命令（status / diff / log / show…）、`ls`/`grep`/`wc` 这类查看命令，以及 Step 2.5 专名核对要用的 WebSearch。**写操作一律不在白名单里**——`git commit`/`push`/`reset`、`rm` 等仍会逐次询问。该文件随 `.claude/` 一起被 gitignore，换机器要重新配。

---

## 二、使用方法 (Usage)

在 Claude Code 会话中打开此文件夹：

```bash
cd "/Users/jialiwu/Desktop/youtube transcript scraper and summary"
claude
```

### 推荐用法：先发链接，拿到选题预判，再决定做不做

直接粘贴 YouTube 链接（先不催）。系统会进入**阶段 -1 选题预判**：抓字幕略读后，以编辑视角给四维加权打分（话题传播度／可沉淀性／可扩展性／独家一手性）+ 受众/定位 + 制作成本，给出"值不值得做、建议哪种形态"的结论，然后**停住等你说"开始转录"**。

```
# 第一步：只发链接 → 得到选题预判
https://youtu.be/am_oeAoUhew

# 第二步：决定要做 → 触发全流程
开始转录
```

### 四种产物形态（由你的措辞路由）

| 形态 | 触发方式 | 适用 |
|---|---|---|
| **图文精读稿**（默认） | 不带关键词，或"图文精读" | 按主题重构、配发布全套要素，直接发公众号 |
| **对话体逐字稿** | 带"逐字稿/对话体/访谈稿/transcript" | 多人访谈，还原现场、标注说话人 |
| **演讲实录（现场回闪）** | 单人演讲/keynote；多嘉宾同题可合成"现场回闪" | 保留演讲者第一人称原话 + 配 PPT 截图 |
| **观察 / 观点稿** | 一个引爆事件 + 多个一手信源，要一条行业判断 | 不走单一视频转写，把多信源编织成自己的中心判断线 |

> 归档文件名必须落在这四种后缀上（`- 图文精读` / `- 逐字稿` / `- 演讲实录` / `- 观察稿`）——`notion_upload.py` 靠后缀识别类型来查重，后缀不认得就会跳过查重、重传留下重复页。

```
# 默认 —— 图文精读稿
帮我把这个视频做成图文精读：https://youtu.be/am_oeAoUhew

# 指定 —— 对话体逐字稿
帮我将这个视频整理为对话体逐字稿：https://youtu.be/am_oeAoUhew
```

确定形态后，系统自动跑完抓取、生成、**对照字幕核校**、Agent Council 互审、归档三件套、Notion 上传，并在每篇目录下留一份**交接文档**供新对话接续——无需额外干预。

---

## 三、工作流全流程 (Workflow)

### 流程主干 → 对应工程模块

收到链接后，整条流水线由 `CLAUDE.md` / `AGENTS.md`（总编排）串起来，逐步如下：

| 步骤 | 做什么 | 闸门 / 路由 | 对应模块 |
|---|---|---|---|
| 前置检查 | 校验三个 API 密钥 | — | `.env` |
| **阶段 -2 播客雷达（可选）** | 说「跑雷达」：扫 20 个频道的 RSS，按相对热度出榜单 + 三档编辑筛选 | 手动触发、不挂定时（脚本零 token，解读才花）；标题层筛选、不抓字幕 | `radar.py` + `radar_channels.json` |
| **阶段 -1 选题预判** | 抓字幕略读 + 四维打分，给结论后**停住等"开始转录"** | 闸门：值不值得投精力做；用 `--prefer-free` 不烧付费配额 | `fetch_transcript.py` + `skills/topic_assessment.md`（批量时 + `skills/transcript_files.md`） |
| **Step 1 抓字幕** | 复用阶段 -1 字幕、校验覆盖率（残缺自动换源重抓） | 闸门：`coverage ≥ 0.9` **且** `coverage_verified` 为 true 才放行 | `fetch_transcript.py` |
| **Step 2 生成内容** | 按形态写稿 | 路由：图文精读 / 逐字稿 / 演讲实录 / 观察稿 | `skills/illustrated_deepdive.md`、`skills/dialogue_transcript.md`、`skills/observation_commentary.md` |
| **Step 2.5 对照字幕核校** | 逐项核对事实/数字/专名/因果（工作流灵魂） | 专名铁律：先查证、拿不准标 ⚠️、绝不臆造；带时间戳的成品先跑机检 | `skills/proper_noun_check.md`、`glossary.md`、`check_transcript_edit.py` |
| **Step 2.6 Agent Council 自检** | 激进 + 保守两位全新审稿人并行打分 → 全新 Judge 裁决 → 主模型按裁决清硬伤 | 闸门：必改硬伤清零 | `skills/reader_facing_review.md`、`skills/council/` |
| **Step 3 归档三件套** | 建中文标题目录，落地成品 + 字幕 + 交接文档 | — | `skills/handoff_doc.md`、`output/<标题>/` |
| **Step 4 上传 Notion** | 上传（重传查重、每类型只留一页、幂等）后读回核对 | 闸门：读回比对不一致不报成功 | `notion_upload.py`、`notion_read.py`、`skills/notion_publish.md` |
| **Step 4.5 精修 + 定稿终审** | 多轮人机精修 + 定稿前再跑 Council；每轮同步更新交接文档 | 闸门：输出"可发布"判定 | `notion_read.py`、`reader_facing_review.md`、`handoff_doc.md` |
| **Step 5 / 5.5 日志 + 棘轮** | 记录执行；有异常/偏差则提报永久规则 | 失败驱动改进 | `skills/meta_harness.md`、`logs/workflow_execution.md`、`logs/system_changelog.md` |
| **Step 6 系统自检与进化** | 盘点本轮改动、更新核心文档 | 触发词驱动（Meta-Harness） | `skills/meta_harness.md`、`CLAUDE.md`、`skills/`、`logs/system_changelog.md` |

> 设计视图（流程步骤按角色着色、右侧映射到工程模块的流水线图）见 → [docs/workflow.svg](docs/workflow.svg)。

### 精编稿体检：`check_transcript_edit.py`

逐字稿 / 演讲实录做完精编压缩后，Step 2.5 之前跑一次（自动在同目录找 `transcript.json`）：

```bash
python3 check_transcript_edit.py "output/<标题>/<标题> - 逐字稿.md"
```

它算两件事：**时间戳单调递增**（出现逆序即 exit 1，属硬伤）和**所有 ≥2 分钟的删除区间**（含开场与片尾），每段附上原字幕摘录，含让步 / 限定语的标 🔺 高风险。脚本只负责算和摆证据，**判断该不该删仍是编辑的活**——理由只能落在四类（广告口播 / 铺垫性长问 / 重复论证 / 纯附和回合），不属于这四类的一律补回。加 `--min-gap <秒>` 调阈值、`--json` 取结构化结果。

> 为什么要有它：精编最危险的失败不是删多了几句，而是整段关键问答被静默删掉、成品读起来依然连贯、自检看不出来。这类必须靠算。

---

> ⚠️ **`output/` 是三件套的唯一本地副本，别当成临时目录清理。** Notion 上只有成品，`transcript.json` 与 `交接文档.md` 只存在于本地，且 `output/` 不进 Git。字幕删了要重抓——花付费配额，老视频还可能已经没有字幕。

### 四层架构

| 层 | 职责 | 模块 |
|---|---|---|
| 选题发现层 | 找出值得预判的候选（相对热度雷达） | `radar.py`、`radar_channels.json` |
| 抓取层 | 拿字幕、保覆盖率 | `fetch_transcript.py` |
| 生成与质控层 | 写稿 + 核校 + 互审 | `skills/*.md`（生成、核校、发布、自进化各规范）+ `glossary.md` |
| 归档发布层 | 三件套 + 上云 | `output/<标题>/`、`notion_upload.py`、`notion_read.py` |
| 自进化层 | 记录 + 棘轮 + 进化 | `logs/*.md`、`system_changelog.md` |

### 设计要点（一句话）

**两道 Agent 闸门夹住"生成"**（Step 2.5 字幕核校 + Step 2.6/4.5 Council 互审）、**三件套 + 交接文档保证可交接**（成品 + `transcript.json` + `交接文档.md`，让新对话只读一页即可接续）、**日志 + 棘轮 + Meta-Harness 让工作流自己迭代自己**。

---

## 四、自定义修改 (Customization)

工作流高度解耦，改规范即改行为。各模块职责：

| 模块 | 管什么 | 想改什么就动它 |
|---|---|---|
| `skills/topic_assessment.md` | 阶段 -1 选题预判 | 四维权重、打分维度、输出格式 |
| `skills/illustrated_deepdive.md` | 图文精读规范 | 9 段式结构、封面 Prompt、减负装置、去 AI 味 |
| `skills/dialogue_transcript.md` | 逐字稿 + 演讲实录规范 | 对话体结构、说话人规则、演讲实录/现场回闪形态 |
| `skills/observation_commentary.md` | 观察 / 观点稿规范 | 中心判断线、多信源编织、冷峻严肃的语体 |
| `skills/reader_facing_review.md` | 复核 + Agent Council 协议 | 互审机制、复核清单 |
| `skills/handoff_doc.md` | 交接文档模板 | 交接文档区块、更新铁律 |
| `skills/transcript_files.md` | 字幕文件命名与存放 | 批量预判命名、pending 目录、summary 导读 |
| `skills/reference_translation.md` | 参考译文使用规范 | 用户提供别家译本时：查漏、找语感，事实回字幕核 |
| `skills/proper_noun_check.md` | 专名核对铁律 | 五条判据、双源参照 |
| `skills/notion_publish.md` | Notion 上传细则 | 查重、本地图片、人工处理的 ⚠️、链接变化 |
| `skills/meta_harness.md` | 棘轮检查 + 系统自检 | Ratchet Check 流程、Step 6 清单 |
| `glossary.md` | 术语对照表 | 统一译法/写法（跨篇、跨系列上下集） |
| `fetch_transcript.py` | 抓取与完整度闸门 | `COVERAGE_THRESHOLD` 阈值、源优先级（`--prefer-free`）|
| `notion_upload.py` | Notion 映射 + 查重 | `create_page()` 字段对齐你的数据库；`TYPE_NAMES` 登记新产物类型；`CALLOUT_ICONS` 增减 callout 触发 emoji |
| `check_transcript_edit.py` | 精编稿体检 | `DEFAULT_MIN_GAP` 缺口阈值、`HEDGE_MARKERS` 让步语词表 |
| `radar.py` | 播客雷达 | `MATURITY_CURVE` 成熟度先验（攒够 3 周数据后应改为按 samples 表拟合）、`BASELINE_MIN_AGE_DAYS` 成熟视频门槛、report 的 `--min-minutes` 短视频阈值 |
| `radar_channels.json` | 雷达监控范围 | 加频道：`python3 radar.py resolve <handle>` 拿 channel_id 后加一行；`weight` 调排序加权；`guest_watchlist` 加值得盯的嘉宾 |
| `http_utils.py` | 网络重试策略 | 重试次数、退避基数、哪些状态码值得重试 |
| `tests/` | 回归测试 | 改完脚本跑 `python3 tests/run_all.py`，新增行为顺手补一条 |

常见改动：

- **更改输出语言：** 编辑对应 skill 的「输出语言」规则。
- **更改文章结构：** 编辑 `illustrated_deepdive.md` 的 9 段式，或 `dialogue_transcript.md` 的格式要求。
- **统一术语译法：** 在 `glossary.md` 增改，核校（Step 2.5）时据此统一全篇及系列上下集。
- **跳过 Notion 上传：** 从 `CLAUDE.md` 删除 Step 4（细则在 `skills/notion_publish.md`，可一并删），并让 `.env` 的 `NOTION_*` 留空。
- **改动任何脚本后：** 跑一遍 `python3 tests/run_all.py`（不依赖 pytest，纯标准库）。这些测试守的都是"不报错、只是悄悄出错"那一类——查重失效、半截字幕放行、正文在上传时变形，光看终端输出发现不了。
- **新增一种产物形态：** 三处都要登记，缺一处就会出问题——① 在对应 skill 里加形态变体（参考"演讲实录"的加法）；② 在 `CLAUDE.md` Step 2 路由 + Step 3 文件名规则处登记；③ 在 `notion_upload.py` 的 `TYPE_NAMES` 里加类型名，否则 Notion 查重认不出它，重传会留下重复页。

---

## 五、API 限制说明

遇到调用失败时，请优先检查以下额度是否耗尽：

| 服务 | 免费额度 / 计费 |
|---|---|
| youtube-transcript.io | 20 个视频 / 月（免费版） |
| youtube-transcript-api | 免费直连 YouTube，无额度（可能被 YouTube 限流） |
| Notion API | 无限制（配合 Integration 使用） |
| Claude Code | 基于你的 Anthropic 订阅计划产生 Token 费用 |

### 省配额：`--prefer-free`

`fetch_transcript.py` 默认付费源优先（稳定性更好），加 `--prefer-free` 则免费源优先、覆盖率达标就收工，**完全不碰付费配额**；免费源残缺或抓不到时才回落付费源兜底。选题预判每条链接都要抓一次字幕，批量预判几条就能吃掉月配额的一大截，所以**阶段 -1 一律用它**：

```bash
python3 fetch_transcript.py <youtube_url> --prefer-free --output transcript_temp.json
```

两种模式都会做覆盖率校验：不足 90% 自动换另一源重抓，两源皆残缺则 exit 1；连视频时长都拿不到时输出 `coverage_verified: false` 与 `warning`，需人工确认，不当作通过。
