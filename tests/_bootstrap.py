"""让 tests/ 下的脚本能直接 import 项目根目录的模块，并提供最小断言工具。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 脚本 import 时会 load_dotenv()，这里给占位值，保证没有 .env 也能跑
os.environ.setdefault("NOTION_API_KEY", "test-key")
os.environ.setdefault("NOTION_DATABASE_ID", "test-db")
os.environ.setdefault("YOUTUBE_TRANSCRIPT_API_KEY", "test-token")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def check(cond, msg: str, detail=None) -> None:
    if not cond:
        raise AssertionError(f"{msg}" + (f"\n     实际：{detail!r}" if detail is not None else ""))
    ok(msg)
