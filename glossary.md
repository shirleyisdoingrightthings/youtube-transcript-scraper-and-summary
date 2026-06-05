# 项目术语对照表（Glossary）

> 本表用于 Step 2.5 对照字幕核校时统一译法与写法，保证**跨篇、跨系列上下集**一致。
> 发现新的高频术语或需要拍板的译法时，在此追加（参照 CLAUDE.md Step 6 Meta-Harness 自检）。

## 一、通用译法规则
- 高共识词保留英文原貌：`Token`、`Agent`、`GPU`、`API`、`Prompt`、`Transformer`、`Scaling Law`、`LLM`。
- 公司 / 产品 / 项目代号保留英文原名：`OpenAI`、`Anthropic`、`Claude`、`Meta`、`DeepMind`、`JEPA`、`AlphaFold`。
- 中文优先用「其他」，不用「其它」。
- 同一段落内，指同一对象的词必须前后统一（典型：「网络」与「编码器」——见下）。

## 二、易混译法（必须统一）

| 英文 / 概念 | 统一译法 | 说明 / 禁用写法 |
|---|---|---|
| embedding vector | 嵌入向量 | 全篇统一；**禁止**和「嵌入表征」混用 |
| embedding | 嵌入 / 嵌入向量 | 指向量时一律「嵌入向量」 |
| representation | 表征 | 「内部表征」「抽象状态表征」；与「嵌入向量」是不同层级，勿混 |
| network / encoder | 网络 / 编码器 | 二者**非同义**：encoder 特指"输入→嵌入"的网络。**同一段内**指同一对象时用词统一（如技术拆解段统一「编码器」），其余语境「网络」正常用；`孪生神经网络` 等固定术语不可改 |
| representation collapse | 表征坍缩 | |
| contrastive learning | 对比学习 | |
| joint embedding | 联合嵌入 | |
| world model | 世界模型 | |
| behavioral cloning | 行为克隆 | |
| hierarchical world model | 分层世界模型 | 与具体实现 `LeWorld Model`（专名，不译）区分开 |

## 三、模型 / 架构名写法（连字符风格统一）

| 统一写法 | 说明 |
|---|---|
| JEPA | 全称 **Joint Embedding Predictive Architecture（联合嵌入预测架构）**，注意"预测"二字不可漏 |
| V-JEPA 2 | 带连字符；全系列（含逐字稿）拉齐为此写法 |
| VL-JEPA | 带连字符 |
| VLA | 视觉-语言-动作模型（Vision-Language-Action） |
| LeWorld Model | 专名，不译、不加括注「分层世界模型」 |
| DINO / DINO V3 | |
| Barlow Twins / VICReg | |

## 四、人名 / 机构（首次出现写法）
- Yann LeCun（图灵奖得主）、Demis Hassabis、Benedict Evans
- Stéphane Deny（带重音符）、Horace Barlow、Alec Radford、Ilya Sutskever
- Meta FAIR、Omni Labs、Physical Intelligence、Welch Labs
