#!/usr/bin/env python3
"""跑全部回归测试：`python3 tests/run_all.py`

不依赖 pytest，纯标准库。每个 test_*.py 也可以单独跑。
这些测试守的都是"不报错、只是悄悄出错"那一类 bug——查重失效、半截字幕放行、
正文内容在上传时变形。改动 fetch_transcript.py / notion_upload.py / http_utils.py 后请务必跑一遍。
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

MODULES = [
    "test_http_retry",
    "test_fetch_coverage",
    "test_notion_dedup",
    "test_markdown_blocks",
    "test_edit_check",
    "test_radar",
]


def main() -> int:
    failed = []
    for name in MODULES:
        mod = __import__(name)
        try:
            mod.main()
        except Exception:                        # noqa: BLE001
            failed.append(name)
            print(f"  ❌ {name} 失败：")
            traceback.print_exc()
        print()

    if failed:
        print(f"❌ {len(failed)}/{len(MODULES)} 组失败：{', '.join(failed)}")
        return 1
    print(f"✅ 全部通过（{len(MODULES)} 组）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
