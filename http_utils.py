#!/usr/bin/env python3
"""统一的 HTTP 退避重试，供 fetch_transcript / notion_upload / notion_read 共用。

为什么需要：
  - 系统代理（127.0.0.1:7897）偶发 SSL 中断，单次请求失败率不低；
  - Notion 有 3 req/s 限流，突发上传会吃到 429；
  - 免费源 youtube-transcript-api 直连 YouTube，也可能被临时限流。

重试策略（只在"重试有意义"时才重试，绝不空转）：
  - 网络异常（超时 / 连接重置 / SSL 中断）→ 重试
  - 429 与 5xx → 重试；429 若带 Retry-After，优先按它等待
  - 其他 4xx（401 密钥错、404 找不到页、400 请求体错）→ 立即返回，重试没有意义
"""
from __future__ import annotations

import os
import sys
import time
import typing

try:
    import requests
except ModuleNotFoundError:
    if os.environ.get("_YT2BLOG_REEXEC") != "1" and os.path.exists("/usr/bin/python3"):
        os.environ["_YT2BLOG_REEXEC"] = "1"
        os.execv("/usr/bin/python3", ["/usr/bin/python3", *sys.argv])
    raise

DEFAULT_RETRIES = 4
DEFAULT_BACKOFF = 1.5          # 退避基数：1.5s, 3s, 6s, 12s
RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    method: str,
    url: str,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
    timeout: int = 30,
    label: str = "",
    **kwargs,
) -> requests.Response:
    """带退避重试的请求。返回 Response；重试用尽仍是网络异常则抛出最后一次异常。

    注意：HTTP 错误码不抛异常，原样返回 Response，由调用方按自己的语义处理。
    """
    tag = f"[{label}] " if label else ""
    last_exc: typing.Optional[Exception] = None

    for attempt in range(retries + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
        except Exception as e:  # noqa: BLE001 —— 网络层什么都可能抛
            last_exc = e
            if attempt == retries:
                raise
            wait = backoff * (2 ** attempt)
            print(f"{tag}网络异常（{type(e).__name__}: {e}），{wait:.0f}s 后重试 "
                  f"（第 {attempt + 1}/{retries} 次）", file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code not in RETRY_STATUS or attempt == retries:
            return resp

        # 429 优先听服务端的 Retry-After
        wait = backoff * (2 ** attempt)
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                wait = max(wait, float(retry_after))
            except ValueError:
                pass
        print(f"{tag}HTTP {resp.status_code}，{wait:.0f}s 后重试 "
              f"（第 {attempt + 1}/{retries} 次）", file=sys.stderr)
        time.sleep(wait)

    if last_exc:
        raise last_exc
    return resp


def get(url: str, **kwargs) -> requests.Response:
    return request_with_retry("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request_with_retry("POST", url, **kwargs)


def patch(url: str, **kwargs) -> requests.Response:
    return request_with_retry("PATCH", url, **kwargs)
