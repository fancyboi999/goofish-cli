"""读取详情页自身发出的响应，校验请求和返回的商品身份。"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .errors import GoofishError, RiskControlError
from .item_data import normalize_item
from .mtop import _classify_error

DETAIL_PATH = "/h5/mtop.taobao.idle.pc.detail/1.0/"


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
            "闲鱼详情需要人工验证；请在沙箱浏览器完成验证后重试，不会自动绕过或重发请求",
            raw=raw,
        ) from exc
    if any(value.partition("::")[0] != "SUCCESS" for value in raw["ret"]):
        raise GoofishError("详情响应不是明确成功状态")
    normalize_item(raw, item_id)
    return raw


class ItemResponse:
    """只消费本次观察到的匹配请求，忽略推荐、验证端点和迟到的旧请求。"""

    def __init__(self, page, item_id: str):
        self.page = page
        self.item_id = item_id
        self.raw: dict | None = None
        self.error: GoofishError | None = None
        self.ready = asyncio.Event()
        self.requests: set[Any] = set()
        self.tasks: set[asyncio.Task] = set()
        self.request_handler = self._request
        self.response_handler = self._schedule
        page.on("request", self.request_handler)
        page.on("response", self.response_handler)

    def _request(self, request) -> None:
        if _matches_request(request, self.item_id):
            self.requests.add(request)

    def _schedule(self, response) -> None:
        if response.request not in self.requests:
            return
        self.requests.discard(response.request)
        task = asyncio.create_task(self._capture(response))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _capture(self, response) -> None:
        try:
            if response.status != 200:
                raise GoofishError(f"详情服务返回 HTTP {response.status}")
            self.raw = _decode_response(await response.text(), self.item_id)
            self.error = None
        except GoofishError as exc:
            self.raw = None
            self.error = exc
        except Exception:
            self.raw = None
            self.error = GoofishError("详情响应读取失败")
        self.ready.set()

    async def wait(self, timeout: float = 20, *, allow_verification: bool = False) -> dict:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            try:
                await asyncio.wait_for(
                    self.ready.wait(), max(0.01, deadline - asyncio.get_running_loop().time())
                )
            except TimeoutError as exc:
                raise GoofishError(
                    "未收到目标商品的成功详情响应；沙箱页面保留，可检查当前页面"
                ) from exc
            self.ready.clear()
            if self.raw is not None:
                return self.raw
            if self.error is not None:
                if allow_verification and isinstance(self.error, RiskControlError):
                    self.error = None
                    continue
                raise self.error

    async def close(self) -> None:
        self.page.remove_listener("request", self.request_handler)
        self.page.remove_listener("response", self.response_handler)
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


async def read_item_page(page, item_id: str) -> dict:
    observer = ItemResponse(page, item_id)
    try:
        await page.goto(f"https://www.goofish.com/item?id={item_id}", wait_until="domcontentloaded")
        return await observer.wait()
    finally:
        await observer.close()


async def fetch_item_page(item_id: str) -> dict:
    from .browser import goofish_page

    async with goofish_page() as page:
        return await read_item_page(page, item_id)
