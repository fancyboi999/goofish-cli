"""item edit-detail — 拉取商品的可编辑草稿（只读）。

接口：mtop.idle.pc.idleitem.editdetail v1.0
用途：编辑前回显现有标题/描述/图片/价格/类目/地址，作为提交编辑的基底。
本命令只读取，不做任何写操作。
"""
from __future__ import annotations

import json
from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call


def _rich_text_plain(rich: Any) -> str:
    """从飞书/草稿富文本结构拼纯文本：同一段落内多个 Text 直接拼接，段落之间换行。"""
    if not rich:
        return ""
    if isinstance(rich, str):
        try:
            decoded = json.loads(rich)
        except ValueError:
            return rich
        # 纯数字 / 布尔 / null 等标量也是合法 JSON，但不是富文本树，原样保留字符串。
        if not isinstance(decoded, (list, dict)):
            return rich
        rich = decoded

    def _paragraphs(node: Any) -> list[str]:
        if isinstance(node, list):
            out: list[str] = []
            for child in node:
                out.extend(_paragraphs(child))
            return out
        if not isinstance(node, dict):
            return []
        if node.get("type") == "Text":
            text = str(node["text"]).strip() if node.get("text") else ""
            return [text] if text else []
        out: list[str] = []
        inline: list[str] = []
        for key in ("children", "elements"):
            sub = node.get(key)
            if not isinstance(sub, list):
                continue
            for child in sub:
                if isinstance(child, dict) and child.get("type") == "Text":
                    if child.get("text"):
                        inline.append(str(child["text"]))
                else:
                    if inline:
                        out.append("".join(inline).strip())
                        inline = []
                    out.extend(_paragraphs(child))
        if inline:
            out.append("".join(inline).strip())
        return [p for p in out if p]

    return "\n".join(_paragraphs(rich))


def _images(image_list: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for img in image_list or []:
        if not isinstance(img, dict) or not img.get("url"):
            continue
        out.append({
            "url": img["url"],
            "width": img.get("widthSize") or img.get("width"),
            "height": img.get("heightSize") or img.get("height"),
            "major": str(img.get("major", "false")).lower() == "true",
        })
    return out


@command(
    namespace="item",
    name="edit-detail",
    description="拉取商品可编辑草稿（只读，编辑前回显图文/价格/类目/地址）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "image_count", "category"],
)
def edit_detail(item_id: str) -> dict[str, Any]:
    if not str(item_id).isdigit():
        raise GoofishError("商品 ID 必须为数字")
    session = Session.load()
    raw = call(
        session,
        api="mtop.idle.pc.idleitem.editdetail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.publish.0.0",
    )
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise GoofishError("编辑草稿响应结构异常")

    text = data.get("itemTextDTO") or {}
    rich_plain = _rich_text_plain(text.get("richTextDesc"))
    price = data.get("itemPriceDTO") or {}
    cat = data.get("itemCatDTO") or {}
    addr = data.get("itemAddrDTO") or {}
    post = data.get("itemPostFeeDTO") or {}

    cents = price.get("priceInCent")
    try:
        price_yuan = f"{int(cents) / 100:.2f}" if cents else None
    except (TypeError, ValueError):
        price_yuan = None

    paragraphs = [p for p in rich_plain.split("\n") if p]
    title = (text.get("title") or "").strip() or (paragraphs[0] if paragraphs else "")
    description = (text.get("desc") or "").strip()
    if not description:
        description = "\n".join(paragraphs[1:]) if len(paragraphs) > 1 else rich_plain

    return {
        "item_id": str(data.get("itemId") or item_id),
        "unique_code": data.get("uniqueCode"),
        "editor_version": data.get("editorVersion"),
        "title": title,
        "description": description,
        "price": price_yuan,
        "original_price": price.get("origPriceInCent"),
        "images": _images(data.get("imageInfoDOList")),
        "image_count": len(_images(data.get("imageInfoDOList"))),
        "category": cat.get("catName"),
        "category_id": cat.get("catId"),
        "address": " ".join(x for x in (addr.get("prov"), addr.get("city"), addr.get("area")) if x),
        "post_fee": post,
        "raw": data,
    }
