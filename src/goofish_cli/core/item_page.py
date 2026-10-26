"""读取详情页自身发出的响应，校验请求和返回的商品身份。"""

from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Error as PlaywrightError

from .errors import AuthRequiredError, GoofishError, RiskControlError
from .item_data import normalize_item
from .mtop import _classify_error

DETAIL_PATH = "/h5/mtop.taobao.idle.pc.detail/1.0/"
_TOKEN_REFRESH_CODES = {"FAIL_SYS_TOKEN_EMPTY", "FAIL_SYS_TOKEN_EXOIRED", "FAIL_SYS_TOKEN_EXPIRED"}


def _matches_request(request, item_id: str) -> bool:
    url = urlsplit(request.url)
    if url.hostname not in {"h5api.m.goofish.com", "h5api.m.taobao.com"} or url.path != DETAIL_PATH:
        return False
    try:
        fields = parse_qs(request.post_data or "")
        if "data" not in fields:
            fields = parse_qs(url.query)
        return str(json.loads(fields["data"][0]).get("itemId")) == item_id
    except (ValueError, KeyError, TypeError, AttributeError):
        return False


def _decode_response(text: str, item_id: str) -> dict:
    if not text.lstrip().startswith("{"):
        match = re.fullmatch(r"\s*[\w.$]+\s*\((.*)\)\s*;?\s*", text, re.S)
        if not match:
            raise GoofishError("详情响应不是可确认的 JSON/JSONP")
        text = match[1]
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise GoofishError("详情响应无法解析") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("ret"), list) or not raw["ret"]:
        raise GoofishError("详情响应缺少明确的业务状态")
    if not all(isinstance(value, str) for value in raw["ret"]):
        raise GoofishError("详情响应业务状态格式无效")
    try:
        _classify_error(raw, "mtop.taobao.idle.pc.detail")
    except RiskControlError as exc:
        raise RiskControlError(
            "闲鱼详情需要人工验证；请在浏览器完成验证后重试，不会自动绕过或重发请求",
            raw=raw,
        ) from exc
    if any(value.partition("::")[0] != "SUCCESS" for value in raw["ret"]):
        raise GoofishError("详情响应不是明确成功状态")
    data = raw.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("itemDO"), dict):
        raise GoofishError("详情响应缺少商品数据")
    if data.get("sellerDO") is not None and not isinstance(data["sellerDO"], dict):
        raise GoofishError("详情响应卖家数据格式无效")
    for field in ("itemLabelExtList", "imageInfos"):
        if data["itemDO"].get(field) is not None and not isinstance(data["itemDO"][field], list):
            raise GoofishError(f"详情响应 {field} 格式无效")
    normalize_item(raw, item_id)
    return raw


class ItemResponse:
    """只消费本次观察到的匹配请求，忽略推荐、验证端点和迟到的旧请求。"""

    def __init__(self, page, item_id: str):
        self.page = page
        self.item_id = item_id
        self.results: asyncio.Queue[dict | GoofishError] = asyncio.Queue()
        self.last_error: GoofishError | None = None
        self.requests: set[Any] = set()
        self.tasks: set[asyncio.Task] = set()
        self.request_handler = self._request
        self.response_handler = self._schedule
        self.failure_handler = self._failed
        self.close_handler = lambda: self.results.put_nowait(GoofishError("商品详情页已关闭"))
        page.on("request", self.request_handler)
        page.on("response", self.response_handler)
        page.on("requestfailed", self.failure_handler)
        page.on("close", self.close_handler)

    def _request(self, request) -> None:
        if _matches_request(request, self.item_id):
            self.requests.add(request)

    def _failed(self, request) -> None:
        self.requests.discard(request)

    def _schedule(self, response) -> None:
        if response.request not in self.requests:
            return
        self.requests.discard(response.request)
        task = asyncio.create_task(self._capture(response))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _capture(self, response) -> None:
        if response.status != 200:
            self.results.put_nowait(GoofishError(f"详情服务返回 HTTP {response.status}"))
            return
        # 导航可能取消响应体读取；只等待页面后续的自然响应，不主动补发请求。
        try:
            text = await response.text()
        except PlaywrightError:
            self.last_error = GoofishError("详情响应读取中断，未收到后续成功响应")
            return
        try:
            result = _decode_response(text, self.item_id)
        except GoofishError as exc:
            ret = (exc.raw or {}).get("ret", [])
            if ret and all(value.partition("::")[0] in _TOKEN_REFRESH_CODES for value in ret):
                # SDK 会自行刷新 token 并重发；中间态不代表用户会话已失效。
                self.last_error = AuthRequiredError("页面令牌刷新未完成", raw=exc.raw)
                return
            result = exc
        self.results.put_nowait(result)

    async def wait(self, timeout: float = 20, *, allow_verification: bool = False) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError
                result = await asyncio.wait_for(
                    self.results.get(), remaining
                )
            except TimeoutError as exc:
                if self.last_error is not None:
                    raise self.last_error from exc
                raise GoofishError(
                    "等待超时，未收到目标商品的成功详情响应；请检查网络及页面是否需要登录或人工验证"
                ) from exc
            if isinstance(result, GoofishError):
                if allow_verification and isinstance(result, RiskControlError):
                    self.last_error = result
                    continue
                raise result
            return result

    async def close(self) -> None:
        self.page.remove_listener("request", self.request_handler)
        self.page.remove_listener("response", self.response_handler)
        self.page.remove_listener("requestfailed", self.failure_handler)
        self.page.remove_listener("close", self.close_handler)
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.requests.clear()


async def read_item_page(page, item_id: str, *, timeout: float = 20) -> dict:
    """导航与取数共享同一截止时间；页面上下文被替换不影响响应观察。"""
    if not math.isfinite(timeout) or timeout <= 0:
        raise GoofishError("详情读取超时必须为有限正数")
    observer = ItemResponse(page, item_id)
    deadline = asyncio.get_running_loop().time() + timeout
    try:
        await page.goto(
            f"https://www.goofish.com/item?id={item_id}",
            wait_until="commit",
            timeout=timeout * 1000,
        )
        return await observer.wait(deadline - asyncio.get_running_loop().time())
    except PlaywrightError as exc:
        raise GoofishError("商品详情页加载失败或超时，请检查网络及浏览器状态") from exc
    finally:
        await observer.close()


async def fetch_item_page(item_id: str) -> dict:
    from .browser import goofish_page

    async with goofish_page() as page:
        return await read_item_page(page, item_id)
