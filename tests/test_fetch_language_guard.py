"""语种校验的回归测试（拉丁字母占比抽检 + 轨道语种偏好）。

守的是这个 bug：youtube-transcript.io 曾把某视频的阿拉伯语自动翻译轨标成
`en` 返回，覆盖率校验完全达标（内容确实完整，只是文种不对），字幕被静默
当成英文交给下游。`fetch_via_io()` 现在对抓到的文本做拉丁字母占比抽检，
占比过低则判定该源本次抓取失败（抛异常），交调用方按既有的"换源重抓"逻辑
处理，绝不静默放行一份文种不对的"英文"字幕。
跑在 `run_all.py` 里时要注意：`test_fetch_coverage.py` 会把 `ft.fetch_via_io`
整个替换成各种假实现，且跑完不还原（它只关心自己的用例）。若不处理，本文件拿到的
`ft.fetch_via_io` 就是上一个测试文件残留的 mock，测不到真正的语种校验逻辑，还会
静默通过——比测试本身缺失更危险。所以每次 `main()` 开头都用 `importlib.reload`
把 `fetch_transcript` 复位到源码定义的原始状态，再开始跑。
"""
import importlib

from _bootstrap import check

import fetch_transcript as ft


ARABIC_SAMPLE = "مرحبا بكم في هذه الحلقة اليوم سنتحدث عن الذكاء الاصطناعي وتطبيقاته المختلفة في الصناعة"
ENGLISH_SAMPLE = "Welcome to today's episode where we talk about artificial intelligence and its applications"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _item_with_tracks(tracks):
    return [{
        "microformat": {"playerMicroformatRenderer": {"lengthSeconds": "600"}},
        "tracks": tracks,
    }]


def _track(text, language=None, n_repeat=30):
    """构造一条轨道：把 text 重复拼成若干带时间戳的分段，语种字段可选。"""
    segs = [{"start": i * 2, "text": text} for i in range(n_repeat)]
    t = {"transcript": segs}
    if language is not None:
        t["language"] = language
    return t


def test_latin_ratio_unit():
    print("── _latin_ratio 单元测试 ──")
    check(ft._latin_ratio(ENGLISH_SAMPLE * 5) > 0.9,
          "纯英文样本拉丁字母占比接近 1", ft._latin_ratio(ENGLISH_SAMPLE * 5))
    ratio = ft._latin_ratio(ARABIC_SAMPLE * 5)
    check(ratio is not None and ratio < 0.1,
          "纯阿拉伯语样本拉丁字母占比接近 0", ratio)
    check(ft._latin_ratio("hi") is None,
          "样本太短（<50 个字母）时返回 None，不当成通过或失败", ft._latin_ratio("hi"))
    # 时间戳格式不应被计入字母统计，也不应干扰占比计算
    tagged = "[00:02] " + ENGLISH_SAMPLE
    check(ft._latin_ratio(tagged) > 0.9,
          "剥离 [MM:SS] 时间戳后再算占比，不受格式干扰", ft._latin_ratio(tagged))


def test_fetch_via_io_rejects_mislabeled_track():
    print("── fetch_via_io：非英文轨道被标成 en 时判定失败 ──")

    # 单条轨道，没有语种字段（复现实例 bug：付费源返回体里就是没有可靠的语种标注），
    # 内容却是阿拉伯语 —— 拉丁字母占比检查必须拦下它，而不是静默当英文放行。
    orig_post = ft.http_utils.post
    try:
        def fake_post(url, **kwargs):
            return _FakeResponse(_item_with_tracks([_track(ARABIC_SAMPLE, language=None)]))

        ft.http_utils.post = fake_post
        try:
            ft.fetch_via_io("dummyid")
            raised, msg = False, None
        except RuntimeError as e:
            raised, msg = True, str(e)
        check(raised, "阿拉伯语轨道（无语种字段）被拒绝，抛出 RuntimeError 而非静默返回")
        check(bool(msg) and ("语种" in msg or "latin" in msg.lower()),
              "报错信息说明了是语种问题，便于人工排查", msg)
    finally:
        ft.http_utils.post = orig_post


def test_fetch_via_io_accepts_clean_english_track():
    print("── fetch_via_io：正常英文轨道照常通过 ──")

    orig_post = ft.http_utils.post
    try:
        def fake_post(url, **kwargs):
            return _FakeResponse(_item_with_tracks([_track(ENGLISH_SAMPLE, language="en")]))

        ft.http_utils.post = fake_post
        text, duration = ft.fetch_via_io("dummyid")
        check(bool(text) and duration == 600,
              "正常英文轨道抓取成功，未被语种检查误伤", (bool(text), duration))
    finally:
        ft.http_utils.post = orig_post


def test_fetch_via_io_prefers_english_tagged_track():
    print("── fetch_via_io：多轨道时优先选 en 标注的那条 ──")

    orig_post = ft.http_utils.post
    try:
        # 第一条轨道语种字段缺失但内容是阿拉伯语，第二条明确标 en 且内容正常。
        # 若沿用旧逻辑"直接取 tracks[0]"，会选中第一条、被语种检查拦下报失败；
        # 修复后应优先选中第二条，正常返回。
        def fake_post(url, **kwargs):
            return _FakeResponse(_item_with_tracks([
                _track(ARABIC_SAMPLE, language=None),
                _track(ENGLISH_SAMPLE, language="en"),
            ]))

        ft.http_utils.post = fake_post
        text, duration = ft.fetch_via_io("dummyid")
        check(bool(text) and "Welcome" in text,
              "多轨道场景下优先选中 en 标注的轨道，而不是排在前面的那条", text[:60])
    finally:
        ft.http_utils.post = orig_post


def main():
    # 上一个测试文件（test_fetch_coverage.py）跑完会把 ft.fetch_via_io /
    # ft.fetch_via_ytapi 等整个换成假实现且不还原，reload 一次拿回真实实现，
    # 否则本文件测的其实是别人留下的 mock，会静默"通过"却什么都没测到。
    importlib.reload(ft)
    test_latin_ratio_unit()
    test_fetch_via_io_rejects_mislabeled_track()
    test_fetch_via_io_accepts_clean_english_track()
    test_fetch_via_io_prefers_english_tagged_track()


if __name__ == "__main__":
    main()
