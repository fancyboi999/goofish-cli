"""验 JS 桥接（pyexecjs + goofish_js_version_2.js）能跑通且 deterministic。"""
from __future__ import annotations


def test_generate_sign_deterministic():
    from goofish_cli.core.sign import generate_sign

    sign1 = generate_sign("1700000000000", "abcdef123456", '{"itemId":"1"}')
    sign2 = generate_sign("1700000000000", "abcdef123456", '{"itemId":"1"}')
    assert sign1 == sign2
    assert isinstance(sign1, str)
    assert len(sign1) == 32  # md5


def test_generate_sign_differs_on_input():
    from goofish_cli.core.sign import generate_sign

    s1 = generate_sign("1700000000000", "abcdef123456", '{"itemId":"1"}')
    s2 = generate_sign("1700000000001", "abcdef123456", '{"itemId":"1"}')
    assert s1 != s2


def test_generate_device_id():
    from goofish_cli.core.sign import generate_device_id

    d1 = generate_device_id("2214350705775")
    # UUID 形式，后缀为 user_id
    assert d1.endswith("-2214350705775")
    assert len(d1.split("-")) == 6  # UUID 5 段 + user_id
