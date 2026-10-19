"""将平台验证交给用户，保留同一沙箱页面并观察真实成功响应。"""

from __future__ import annotations

import argparse
import asyncio
import sys
from urllib.parse import parse_qs, urlsplit

from goofish_cli.core.browser import goofish_page
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.item_page import ItemResponse


async def verify_item(item_id: str, timeout: int) -> None:
    async with goofish_page() as page:
        observer = ItemResponse(page, item_id)
        try:
            current = urlsplit(page.url)
            if (
                current.hostname != "www.goofish.com"
                or current.path != "/item"
                or parse_qs(current.query).get("id") != [item_id]
            ):
                await page.goto(
                    f"https://www.goofish.com/item?id={item_id}", wait_until="domcontentloaded"
                )
            print(
                "请在沙箱内完成平台验证；若页面已显示商品，可手动刷新一次。不会自动解题或重试。",
                flush=True,
            )
            await observer.wait(timeout, allow_verification=True)
            print("已收到目标商品的成功详情响应，验证状态保留在当前沙箱浏览器。", flush=True)
        finally:
            await observer.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("item_id")
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()
    if not args.item_id.isdigit() or not 30 <= args.timeout <= 3600:
        parser.error("商品 ID 或超时无效")
    try:
        asyncio.run(verify_item(args.item_id, args.timeout))
    except GoofishError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(exc.exit_code) from exc


if __name__ == "__main__":
    main()
