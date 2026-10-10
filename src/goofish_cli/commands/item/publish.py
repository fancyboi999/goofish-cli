"""item publish — 发布新商品。

流程：upload_images → category.recommend → location.default → publish
接口：mtop.idle.pc.idleitem.publish v1.0（写操作）
"""

import json
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from goofish_cli.commands.category.recommend import recommend
from goofish_cli.commands.location.default import default as get_default_location
from goofish_cli.commands.media.upload import upload, validate_image_path, validate_image_receipt
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError, PartialResultError
from goofish_cli.core.guard import watch
from goofish_cli.core.mtop import call
from goofish_cli.core.write_operation import write_operation


@command(
    namespace="item",
    name="publish",
    description="发布商品（自动识别类目 + 默认地址），价格单位元",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "cat_name", "ok"],
    write=True,
    arguments=["images", "price"],
)
def publish(
    title: str,
    desc: str,
    images: list[str] | None = None,
    *,
    price: float,
    original_price: float | None = None,
    delivery: Literal["包邮", "按距离计费", "一口价", "无需邮寄"] = "无需邮寄",
    post_price: float = 0,
    can_self_pickup: bool = True,
    images_json: str = "[]",
    category_json: str = "",
    location_json: str = "",
) -> dict[str, Any]:
    # 所有确定性的输入错误在任何上传或经营提交前拒绝。
    if not title.strip() or not desc.strip():
        raise GoofishError("标题和描述不能为空")
    _money(price)
    _money(post_price)
    if original_price is not None:
        _money(original_price)
    try:
        prepared = json.loads(images_json)
        cat = json.loads(category_json) if category_json else None
        loc = json.loads(location_json) if location_json else None
    except ValueError:
        raise GoofishError("图片、类目或地址 JSON 格式无效") from None
    if not isinstance(prepared, list):
        raise GoofishError("images-json 必须是上传图片收据数组")
    infos = [validate_image_receipt(value) for value in prepared]
    paths = [validate_image_path(path) for path in images or []]
    if not 1 <= len(infos) + len(paths) <= 9:
        raise GoofishError("发布必须有 1–9 张图片，可使用本地文件或上传收据")
    if cat is not None:
        _category(cat)
    if loc is not None:
        _address(loc)
    session = Session.load()
    stage = "upload"
    attempted = False
    try:
        with watch(account=session.unb):
            for path in paths:
                infos.append(upload(str(path)))
            stage = "category"
            cat = cat if cat is not None else recommend(title, json.dumps(infos))
            stage = "location"
            loc = loc if loc is not None else get_default_location()
            _category(cat)
            _address(loc)
            data = _build_publish_data(title=title, desc=desc, image_infos=infos, price=price,
                                       original_price=original_price, delivery=delivery,
                                       post_price=post_price, can_self_pickup=can_self_pickup,
                                       cat_info=cat, location=loc)
            stage = "submit"
            with write_operation(session, "item.write"):
                attempted = True
                raw = call(session, api="mtop.idle.pc.idleitem.publish", data=data,
                           version="1.0", spm_cnt="a21ybx.publish.0.0")
            result = raw.get("data") if isinstance(raw, dict) else None
            item_id = result.get("itemId") if isinstance(result, dict) else None
            if item_id is None or not str(item_id).strip():
                raise ValueError("missing_item_id")
    except (GoofishError, OSError, ValueError, TypeError, AttributeError) as exc:
        unknown = attempted and not isinstance(exc, GoofishError)
        status = "submission_unknown" if unknown else "submission_rejected" if attempted else "not_submitted"
        message = "发布结果未知；先核对自己的商品列表，勿自动重复发布" if unknown else str(exc) if isinstance(exc, GoofishError) else "发布准备响应结构或连接失败，未提交商品"
        progress = {"images": infos, "category": {k: v for k, v in (cat or {}).items() if k != "raw"},
                    "location": loc, "status": status, "failed_stage": stage,
                    "requires_readback": unknown}
        error = {"error_type": type(exc).__name__, "phase": stage, "submission_status": status}
        if hasattr(exc, "retry_after"):
            error["retry_after"] = exc.retry_after
        raise PartialResultError(message, progress, error, exit_code=getattr(exc, "exit_code", 1)) from exc
    return {"item_id": str(item_id), "title": title, "price": price,
            "cat_name": cat["cat_name"], "ok": True,
            "status": "accepted", "requires_readback": True, "images": infos}


def _money(value: float) -> str:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise GoofishError("金额必须是有效数字") from None
    try:
        valid = amount.is_finite() and amount >= 0 and amount == amount.quantize(Decimal("0.01"))
    except InvalidOperation:
        valid = False
    if not valid:
        raise GoofishError("金额必须非负且最多两位小数")
    return str(int(amount * 100))


def _category(value: Any) -> None:
    if not isinstance(value, dict) or any(not value.get(k) for k in ("cat_id", "cat_name", "channel_cat_id", "tb_cat_id")):
        raise GoofishError("已确认类目必须包含 cat_id/cat_name/channel_cat_id/tb_cat_id")


def _address(value: Any) -> dict:
    if not isinstance(value, dict):
        raise GoofishError("发布地址必须是 location default 的 DTO")
    selected = value.get("selected")
    if selected is None:
        addresses = value.get("all") or []
        selected = next((x for x in addresses if isinstance(x, dict) and str(x.get("divisionId", "")) == str(value.get("division_id", ""))), None)
    if not isinstance(selected, dict) or not selected.get("divisionId"):
        raise GoofishError("未确认发布地址，请提供 location-json")
    return selected


def _build_publish_data(
    *,
    title: str,
    desc: str,
    image_infos: list[dict[str, Any]],
    price: float,
    original_price: float | None,
    delivery: str,
    post_price: float,
    can_self_pickup: bool,
    cat_info: dict[str, Any],
    location: dict[str, Any],
) -> dict[str, Any]:
    image_do_list = [
        {
            "extraInfo": {"isH": "false", "isT": "false", "raw": "false"},
            "isQrCode": False,
            "url": img["url"],
            "heightSize": img["height"],
            "widthSize": img["width"],
            "major": index == 0,
            "type": 0,
            "status": "done",
        }
        for index, img in enumerate(image_infos)
    ]

    post_fee: dict[str, Any] = {
        "canFreeShipping": False,
        "supportFreight": False,
        "onlyTakeSelf": False,
    }
    if delivery == "包邮":
        post_fee["canFreeShipping"] = True
        post_fee["supportFreight"] = True
    elif delivery == "按距离计费":
        post_fee["supportFreight"] = True
        post_fee["templateId"] = "-100"
    elif delivery == "一口价":
        post_fee["supportFreight"] = True
        post_fee["postPriceInCent"] = _money(post_price)
        post_fee["templateId"] = "0"
    elif delivery == "无需邮寄":
        post_fee["templateId"] = "0"

    price_dto: dict[str, str] = {}
    default_price = price <= 0
    if not default_price:
        price_dto["priceInCent"] = _money(price)
    if original_price and original_price > 0:
        price_dto["origPriceInCent"] = _money(original_price)

    first = _address(location)
    item_addr = {
        "area": first.get("area", ""), "city": first.get("city", ""),
        "divisionId": first.get("divisionId", ""),
        "gps": f"{first.get('longitude', '')},{first.get('latitude', '')}",
        "poiId": first.get("poiId", ""), "poiName": first.get("poi", ""),
        "prov": first.get("prov", ""),
    }

    return {
        "freebies": False,
        "itemTypeStr": "b",
        "quantity": "1",
        "simpleItem": "true",
        "imageInfoDOList": image_do_list,
        "itemTextDTO": {"desc": desc, "title": title, "titleDescSeparate": True},
        "itemLabelExtList": [],
        "itemPriceDTO": price_dto,
        "userRightsProtocols": [{"enable": False, "serviceCode": "SKILL_PLAY_NO_MIND"}],
        "itemPostFeeDTO": post_fee,
        "itemAddrDTO": item_addr,
        "defaultPrice": default_price,
        "itemCatDTO": {
            "catId": cat_info["cat_id"],
            "catName": cat_info["cat_name"],
            "channelCatId": cat_info["channel_cat_id"],
            "tbCatId": cat_info["tb_cat_id"],
        },
        "onlyTakeSelf": can_self_pickup,
        "uniqueCode": cat_info.get("unique_code") or str(time.time_ns() // 1000),
        "sourceId": "pcMainPublish",
        "bizcode": "pcMainPublish",
        "publishScene": "pcMainPublish",
    }
