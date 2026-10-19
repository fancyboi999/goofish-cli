"""自然详情响应必须与本次请求匹配，平台验证不能被当作成功或静默重试。"""

import asyncio
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from goofish_cli.commands.item.view import _view_result
from goofish_cli.core.errors import GoofishError, RiskControlError
from goofish_cli.core.item_page import ItemResponse, _decode_response, _matches_request


def payload(item_id="123", price=0):
    return {
        "ret": ["SUCCESS::调用成功"],
        "data": {
            "itemDO": {
                "itemId": item_id,
                "title": "test",
                "soldPrice": price,
            },
            "sellerDO": {"sellerId": 456, "nick": "test seller"},
        },
    }


def request(item_id="123", host="h5api.m.goofish.com", path="/h5/mtop.taobao.idle.pc.detail/1.0/"):
    return SimpleNamespace(
        url="https://" + host + path, post_data=urlencode({"data": json.dumps({"itemId": item_id})})
    )


@pytest.mark.parametrize(
    "host,path,item_id",
    [
        ("evil.example", "/h5/mtop.taobao.idle.pc.detail/1.0/", "123"),
        ("h5api.m.goofish.com", "/_____tmd_____/punish", "123"),
        ("h5api.m.goofish.com", "/h5/mtop.taobao.idle.pc.detail/1.0/", "124"),
    ],
)
def test_unrelated_request_is_ignored(host, path, item_id):
    assert not _matches_request(request(item_id, host, path), "123")


def test_matching_query_and_post_requests():
    assert _matches_request(request(), "123")
    req = request()
    req.url += "?" + req.post_data
    req.post_data = None
    assert _matches_request(req, "123")


@pytest.mark.parametrize("wrapper", ["{}", "mtopjsonp1({});"])
def test_json_and_jsonp_validate_identity_and_keep_zero_price(wrapper):
    raw = _decode_response(wrapper.format(json.dumps(payload())), "123")
    assert _view_result(raw, "123")["price"] == "¥0"
    with pytest.raises(GoofishError, match="身份"):
        _decode_response(wrapper.format(json.dumps(payload("124"))), "123")


@pytest.mark.parametrize("ret", [[], ["NOT_SUCCESS"], ["SUCCESSFUL"], [3], None])
def test_requires_explicit_success(ret):
    raw = payload()
    raw["ret"] = ret
    with pytest.raises(GoofishError):
        _decode_response(json.dumps(raw), "123")


def test_platform_challenge_has_risk_exit_code():
    with pytest.raises(RiskControlError) as exc:
        _decode_response(json.dumps({"ret": ["FAIL_SYS_USER_VALIDATE::RGV587_ERROR"]}), "123")
    assert exc.value.exit_code == 76
    assert "人工验证" in str(exc.value)


class Page:
    def __init__(self):
        self.handlers = {}

    def on(self, event, handler):
        self.handlers[event] = handler

    def remove_listener(self, event, handler):
        assert self.handlers.pop(event) == handler


async def test_late_response_is_ignored_and_listeners_are_removed():
    page = Page()
    observer = ItemResponse(page, "123")
    # 请求未在当前观察器中出现，不能接受之前页面迟到的响应。
    observer._schedule(SimpleNamespace(request=object()))
    with pytest.raises(GoofishError, match="未收到"):
        await observer.wait(0.01)
    assert not observer.tasks
    await observer.close()
    assert not page.handlers


async def test_manual_challenge_waits_for_new_success_without_issuing_requests():
    page = Page()
    observer = ItemResponse(page, "123")

    async def body(raw):
        return json.dumps(raw)

    risk = SimpleNamespace(
        status=200, text=lambda: body({"ret": ["FAIL_SYS_USER_VALIDATE::RGV587_ERROR"]})
    )
    success = SimpleNamespace(status=200, text=lambda: body(payload()))
    await observer._capture(risk)
    waiter = asyncio.create_task(observer.wait(1, allow_verification=True))
    await asyncio.sleep(0)
    await observer._capture(success)
    assert (await waiter)["data"]["itemDO"]["itemId"] == "123"
    await observer.close()
