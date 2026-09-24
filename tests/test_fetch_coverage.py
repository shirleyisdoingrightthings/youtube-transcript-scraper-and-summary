"""字幕完整度闸门与 --prefer-free 的回归测试。

守的是这个 bug：终判原先写作 `if duration and ...`，付费源整体失败或返回体缺
microformat 时 duration 为 None，完整度校验被短路跳过——半截字幕零校验放行，
正是这个脚本存在的理由被绕过。
"""
import contextlib
import io
import json
import os
import sys
import tempfile

from _bootstrap import check

import fetch_transcript as ft

FULL = "\n".join(f"[{m:02d}:00] line {m}" for m in range(0, 48))   # 到 47:00
HALF = "\n".join(f"[{m:02d}:00] line {m}" for m in range(0, 24))   # 到 23:00
DURATION = 2860                                                    # 47:40
URL = "https://youtu.be/abcdefghijk"

paid_calls: list = []


def _run(argv):
    """跑一次 main()，返回 (exit_code, stdout_json, stderr)。"""
    out, err, code = io.StringIO(), io.StringIO(), 0
    paid_calls.clear()
    sys.argv = ["fetch_transcript.py"] + argv
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            ft.main()
    except SystemExit as e:
        code = e.code
    return code, json.loads(out.getvalue()), err.getvalue()


def _paid(text, duration, description=None):
    def _f(video_id):
        paid_calls.append(video_id)
        return text, duration, description
    return _f


def _free(text, lang="en"):
    return lambda video_id: (text, lang)


def setup():
    ft.API_AUTH = "Basic test-token"
    ft.get_video_title = lambda vid: "测试视频"
    ft.get_video_description = lambda vid: None


def test_coverage_gate():
    # 付费源整体失败 + 时长也拿不到 → 不得静默放行
    ft.fetch_via_io = lambda vid: (_ for _ in ()).throw(RuntimeError("500"))
    ft.fetch_via_ytapi = _free(HALF)
    ft.get_video_duration = lambda vid: None
    code, data, err = _run([URL])
    check(code == 0 and data["coverage"] is None and data["coverage_verified"] is False
          and bool(data["warning"]) and "无法校验字幕完整度" in err,
          "时长不可得 → coverage_verified=false + 告警（修复前是静默 null 放行）", data)

    # 付费源半截、microformat 无时长，但观看页补到时长 → 触发换源并拿到全量
    ft.fetch_via_io = _paid(HALF, None)
    ft.fetch_via_ytapi = _free(FULL)
    ft.get_video_duration = lambda vid: DURATION
    code, data, err = _run([URL])
    check(code == 0 and data["source"] == "youtube-transcript-api"
          and data["coverage_verified"] and data["coverage"] > 0.9,
          "付费源半截且无时长 → 补抓时长后换源，拿到完整字幕", data)

    # 两源都半截 → 硬失败
    ft.fetch_via_io = _paid(HALF, DURATION)
    ft.fetch_via_ytapi = _free(HALF)
    code, data, err = _run([URL])
    check(code == 1 and data["coverage"] < 0.9 and data["error"],
          "两源皆残缺 → exit 1，绝不把半截字幕交给下游", data)


def test_source_priority():
    ft.get_video_duration = lambda vid: DURATION

    # 默认：付费源优先
    ft.fetch_via_io = _paid(FULL, DURATION)
    ft.fetch_via_ytapi = _free(FULL)
    code, data, _ = _run([URL])
    check(code == 0 and data["source"] == "youtube-transcript.io" and paid_calls,
          "默认仍是付费源优先（稳定性更好）", data["source"])

    # --prefer-free：免费源达标 → 一次都不碰付费源
    code, data, err = _run([URL, "--prefer-free"])
    check(code == 0 and data["source"] == "youtube-transcript-api" and paid_calls == []
          and "不消耗付费源配额" in err,
          "--prefer-free 免费源达标 → 付费源调用 0 次（省 20/月 的配额）", paid_calls)

    # --prefer-free：免费源残缺 → 仍回落付费源兜底
    ft.fetch_via_ytapi = _free(HALF)
    code, data, _ = _run([URL, "--prefer-free"])
    check(code == 0 and data["source"] == "youtube-transcript.io" and paid_calls,
          "--prefer-free 免费源残缺 → 回落付费源兜底", data["source"])

    # 没配 key 时免费源够用就照跑
    ft.API_AUTH = ""
    ft.fetch_via_ytapi = _free(FULL, "zh-Hans")
    code, data, _ = _run([URL, "--prefer-free"])
    check(code == 0 and data["language"] == "zh-Hans",
          "无 API key + --prefer-free 仍可跑通，且记录字幕语言", data["language"])
    ft.API_AUTH = "Basic test-token"

    # --output 与 --prefer-free 混用，参数解析不打架
    ft.fetch_via_ytapi = _free(FULL)
    tmp = os.path.join(tempfile.mkdtemp(), "out.json")
    code, _, _ = _run([URL, "--prefer-free", "--output", tmp])
    with open(tmp, encoding="utf-8") as f:
        saved = json.load(f)
    check(code == 0 and saved["source"] == "youtube-transcript-api",
          "--prefer-free 与 --output 混用正常", saved["source"])


def main():
    print("── 字幕完整度闸门 / 源优先级 ──")
    setup()
    test_coverage_gate()
    test_source_priority()


if __name__ == "__main__":
    main()
