- **2026-05-19**：根据用户基于 Notion 范本（Jim Fan 那期）提出的结构升级建议，对 `skills/dialogue_transcript.md` 进行大幅重构。主要变更：①新增"开篇引言（blockquote）"作为首部钩子，要求一句来自嘉宾本人、最具判断力的金句；②新增"视频价值段"，定位为编辑视角的价值判断而非内容摘要（3-5 句上限）；③简化"嘉宾背景"至 1-2 句；④升级"核心观点"为命名化概念清单（每条必须是"有名字的"概念，而非描述性标题），条数无上限；⑤将逐字稿章节标题从功能性切换为叙事性（明确禁用"关于 X 的讨论"类标题）；⑥新增媒体占位符标准（🖼️ 图片占位、🎞️ GIF 占位）；⑦新增"翻译质量与受众平衡"章节（专业性 + 可读性双底线，照顾从业者与文科背景普通读者）；⑧新增完成后必须执行的"审稿人自检 Checklist"（A 嘉宾背景准确性 / B 开篇引言与视频价值 / C 核心观点完整性 / D 翻译准确性 / E 标题与内容对应）。
- **2026-05-12**：触发 Ratchet Check（Step 5.5），在 `skills/dialogue_transcript.md` 中补充和修正了逐字稿的格式规范：访谈信息统一使用中文冒号，核心观点数字列表标题加粗并提行正文，增加“以下为逐字稿正文：”二级标题，规范说话人标签后的单个空格。
- **2026-05-12**：优化 `skills/dialogue_transcript.md` 输出结构（移除内容概述和重点关注），合并原重点关注至核心观点，并放开核心观点 3-5 条的上限限制（长访谈可达 8-10 条）；同步在 `skills/article_generation.md` 放开条数限制。
# System Changelog (Meta-Harness)

> 此日志文件用于记录 `YouTube Transcript Scraper and Summary` 系统框架本身的演进与维护。
> 当触发 Meta-Harness 自检协议（Step 6）时，由 Agent 根据用户的批准在此记录：架构优化、规则重构、脚本升级及目录结构变动。

---

## [2026-05-06]
- **升级模块**：`CLAUDE.md`
- **变更详情**：
  1. **(Fix 1) Success Silence — 输出信号规范**：在 Step 1、Step 3、Step 4（Notion + Obsidian）各自新增"输出信号（Output Signal）"规范。成功路径仅输出一行简报，不返回 JSON、page ID 或完整 API 响应体；失败路径输出完整错误信息，等待用户确认后再处理。目标：降低 context 信噪比，防止 agent 因冗余确认信息失去焦点。
  2. **(Fix 2) Ratchet Check — 棘轮检查协议（Step 5.5）**：新增 Step 5.5，在每次工作流执行结束后自动触发轻量级自检。满足触发条件（运行异常、用户修正、降级路径）时，起草永久规则并向用户请求确认写入；用户确认后立即更新 CLAUDE.md 或 article_generation.md，并记录本 changelog。无异常时保持沉默。目标：将 failure-driven 规则积累变成系统性机制，而非依赖用户手动触发 Meta-Harness Protocol。

---

## [2026-04-23]
- **升级模块**：`CLAUDE.md`, `README.md`, `tags.json`, `notion_upload.py`, `skills/article_generation.md`
- **变更详情**：
  1. **(Phase 1) 上下文持久化基建**：引入 `tags.json` 强约束标签发散行为；建立 `logs/` 机制提升系统可观测性；打通 Obsidian `Second Brain` 的 Markdown 双向同步路径。
  2. **(Phase 2) 极简收纳与分类降级**：确立了“本地文件夹不带标签前缀、直接使用完整自然命名”的规则。将标签属性全面转移至标准的 YAML Frontmatter，并同步优化了 `notion_upload.py`，使其能自动跳过 YAML 块。
  3. **(Phase 3) 知识网分层治理**：确立了 **“宏观分类用 YAML Tags 强收敛，微观术语用 Obsidian 双链 `[[ ]]` 自由发散”** 的核心分类准则，并在生成规范中禁用了正文内的 `# 一级标题`。
  4. **(Phase 4) Meta-Harness 自进化协议**：在大纲内新增了触发式的自检 Checklist，允许系统在发生架构改动后主动提出更新 README 等文档的建议并记入本系统日志。
