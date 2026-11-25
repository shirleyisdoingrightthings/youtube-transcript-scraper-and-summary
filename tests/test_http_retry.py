"""统一退避重试的回归测试。

要点：该重试的重试（网络异常 / 429 / 5xx），不该重试的立刻返回（401/404 之类
客户端错误重试多少次都是同样的结果，只会白等）。
"""
from _bootstrap import check

import http_utils


class FakeResp:
    def __init__(self, status_code, headers=None):
        self.status_code = status_code
        self.headers = headers or {}
        self.ok = status_code < 400


def _patch(sequence):
    """把 requests.request 换成按 sequence 依次吐出结果的假实现，并吃掉 sleep。"""
    calls = {"n": 0, "slept": []}
    items = list(sequence)

    def fake_request(method, url, **kwargs):
        calls["n"] += 1
        item = items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    http_utils.requests.request = fake_request
    http_utils.time.sleep = lambda s: calls["slept"].append(s)
    return calls


def test_retries_on_transient():
    calls = _patch([FakeResp(429), FakeResp(503), FakeResp(200)])
    resp = http_utils.get("https://example.com", label="t")
    check(resp.status_code == 200 and calls["n"] == 3,
          "429 / 503 会退避重试，直到成功", calls["n"])
    check(calls["slept"] == sorted(calls["slept"]) and len(calls["slept"]) == 2,
          "等待时间逐次拉长（指数退避）", calls["slept"])


def test_respects_retry_after():
    calls = _patch([FakeResp(429, {"Retry-After": "30"}), FakeResp(200)])
    http_utils.get("https://example.com")
    check(calls["slept"] == [30.0], "429 带 Retry-After 时听服务端的", calls["slept"])


def test_no_retry_on_client_error():
    for code in (400, 401, 404):
        calls = _patch([FakeResp(code), FakeResp(200)])
        resp = http_utils.get("https://example.com")
        check(resp.status_code == code and calls["n"] == 1,
              f"{code} 立即返回、不浪费时间重试", calls["n"])


def test_retries_on_network_exception():
    calls = _patch([OSError("SSL EOF"), OSError("SSL EOF"), FakeResp(200)])
    resp = http_utils.get("https://example.com")
    check(resp.status_code == 200 and calls["n"] == 3,
          "网络异常（代理 SSL 中断）会重试", calls["n"])

    calls = _patch([OSError("boom")] * 10)
    try:
        http_utils.get("https://example.com", retries=2)
        raised = False
    except OSError:
        raised = True
    check(raised and calls["n"] == 3, "重试用尽仍失败 → 把异常抛给调用方", calls["n"])


def main():
    print("── HTTP 退避重试 ──")
    import requests as _real                      # noqa: F401
    orig_request, orig_sleep = http_utils.requests.request, http_utils.time.sleep
    try:
        test_retries_on_transient()
        test_respects_retry_after()
        test_no_retry_on_client_error()
        test_retries_on_network_exception()
    finally:
        http_utils.requests.request, http_utils.time.sleep = orig_request, orig_sleep


if __name__ == "__main__":
    main()
