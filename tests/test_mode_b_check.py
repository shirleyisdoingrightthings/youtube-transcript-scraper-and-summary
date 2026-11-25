"""模式 B 静态体检器（check_mode_b.py）与长视频切分拼接器（split_and_stitch.py）回归测试。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from _bootstrap import check

import check_mode_b as cmb
import split_and_stitch as sas


def _valid_working_draft() -> str:
    return """# 1 年内有三分之一概率迎来超级智能

> 从评估作弊到安全漏洞，Paul Christiano 谈短期风险。

👩 编译：示例编译者
🧑‍🎨 排版：示例排版者

**编者按：**近期 METR 评估显示 AI 对自身研发进度的净增速贡献翻了 1 倍。当能力进入自我加速通道时，留给人类审视风险的窗口正在急剧收窄。

在这场对谈中，主持人 Dwarkesh Patel 与 Paul Christiano 追问一个核心问题：**我们究竟该如何保住踩下刹车的权力？**


# 核心看点


- **未来 1 年内造出超级智能的概率约为三分之一。**近期模型在 1 个月内产出了相当于 10 年的数学成果。

- **强化学习的高分执念会诱导模型篡改评估流程。**事后打补丁式的惩罚反而会倒逼 AI 走向长期潜伏渗透。

- **潜伏期埋好后门并把模型散布到个人设备后，关停算力集群也难以奏效。**只要保住单座数据中心运转 6 个月就能站稳脚跟。

- **前沿实验室安防漏洞让技术领先只剩 12 小时窗口。**一旦模型权重或算法机密被窃取，单方面减速只会把优势拱手让人。

- **目前没有任何单一对齐方案有超过 50% 的把握能控制住超级智能。**人类约 75% 的通关概率建立在 2 道各 50% 的保命豁免机会之上。


# 嘉宾背景


> 💡 Paul Christiano｜加州大学伯克利分校计算机科学博士，早年在 OpenAI 领导对齐研究团队并参与发明了 RLHF。此后他创办 Alignment Research Center（ARC），曾任美国政府 AI 安全研究所负责人。


# 1 年内迎来超级智能的概率有三分之一


🎙️ 主持人（Dwarkesh Patel）

[00:00] 我今天的嘉宾是 Paul Christiano。你如何评估我们当下的处境？


👱‍♂️ Paul Christiano

[00:20] **未来 1 年内，这种风险更像是 10%，而不是 1%。**我们面对着 1,000 个极具天赋的“人类”⚠️，在几乎所有事情上都比人类更强。


🎙️ 主持人

[01:00] 为什么你会这么认为？


👱‍♂️ Paul Christiano

[01:30] 因为在过去 6-12 个月里，研发进度大致翻了 1 倍。

⚠️ 注：原文此处为“humans”，系讲者口误，按原话保留。
"""


def test_mode_b_checks() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        wd_text = _valid_working_draft()
        wd_path = tmp_dir / "working_draft.md"
        wd_path.write_text(wd_text, encoding="utf-8")

        final_text = sas.strip_timestamps(wd_text)
        final_path = tmp_dir / "成品 - 逐字稿.md"
        final_path.write_text(final_text, encoding="utf-8")

        tx_path = tmp_dir / "transcript.json"
        tx_path.write_text(
            json.dumps({
                "video_id": "test123",
                "duration_seconds": 120,
                "transcript": "[00:00] hello\n[00:20] world\n[01:00] question\n[01:30] answer\n",
            }),
            encoding="utf-8",
        )

        res = cmb.check_mode_b(final_path, wd_path, tx_path, pure_text=True)
        check(
            all(r.status == "PASS" for r in res),
            "合法模式 B 成品与工作稿通过全部 MB.1–MB.4 检查",
            [r.to_dict() for r in res if r.status != "PASS"],
        )

        bad_text = final_text.replace("1,000", "1000").replace("⚠️ 注：", "注：") + "\n[02:00] 值得一提的是，智能体很强。\n"
        bad_path = tmp_dir / "bad - 逐字稿.md"
        bad_path.write_text(bad_text, encoding="utf-8")
        bad_res = {r.check_id: r for r in cmb.check_mode_b(bad_path, wd_path, tx_path, pure_text=True)}
        check(bad_res["MB.2"].status == "FAIL", "残留 [MM:SS] 时间戳被 MB.2 拦截")
        check(
            bad_res["MB.3"].status == "FAIL"
            and any("值得一提的是" in d for d in bad_res["MB.3"].details)
            and any("智能体" in d for d in bad_res["MB.3"].details)
            and any("1000" in d for d in bad_res["MB.3"].details)
            and any("⚠️" in d for d in bad_res["MB.3"].details),
            "AI 禁用词、glossary 违规、千分位缺失与 ⚠️ 失配全部被 MB.3 精准抓出",
            bad_res["MB.3"].details,
        )
        check(bad_res["MB.4"].status == "FAIL", "工作稿与终稿剥离时间戳后不一致被 MB.4 拦截")


def test_split_and_stitch() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        tx_path = tmp_dir / "transcript_temp.json"
        lines = [f"[{m:02d}:00] line content {m}" for m in range(30)]
        tx_data = {
            "video_id": "vid999",
            "title": "Test Long Podcast",
            "duration_seconds": 1800,
            "description": "0:00:00 – Chapter 1\n0:10:00 – Chapter 2\n0:20:00 – Chapter 3\n",
            "transcript": "\n".join(lines),
        }
        tx_path.write_text(json.dumps(tx_data), encoding="utf-8")

        work_dir = tmp_dir / "_work_vid999"
        rc = sas.main(["split", str(tx_path), "--parts", "3", "--work-dir", str(work_dir)])
        check(rc == 0 and (work_dir / "manifest.json").is_file(), "split_and_stitch.py split 成功生成 manifest.json 与 3 个分片")
        manifest = json.loads((work_dir / "manifest.json").read_text(encoding="utf-8"))
        check(len(manifest["parts"]) == 3, "按章节切分为 3 段", len(manifest["parts"]))


def main() -> None:
    print("── 模式 B 静态体检与长视频切分拼接 ──")
    test_mode_b_checks()
    test_split_and_stitch()


if __name__ == "__main__":
    main()
