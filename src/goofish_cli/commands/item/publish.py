"""item publish — 发布新商品。

流程：upload_images → category.recommend → location.default → publish
接口：mtop.idle.pc.idleitem.publish v1.0（写操作）
"""

import json
from typing import Any, Literal

from goofish_cli.commands.category.recommend import recommend
from goofish_cli.commands.location.default import default as get_default_location
from goofish_cli.commands.media.upload import upload
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.guard import watch
from goofish_cli.core.limiter import acquire
from goofish_cli.core.mtop import call


@command(
    namespace="item",
    name="publish",
    description="发布商品（自动识别类目 + 默认地址），价格单位元",
    strategy=Strategy.COOKIE,
    columns=["item_id", "title", "price", "cat_name", "ok"],
    write=True,
)
def publish(
    title: str,
    desc: str,
    images: list[str],
    price: float,
    original_price: float | None = None,
    delivery: Literal["包邮", "按距离计费", "一口价", "无需邮寄"] = "无需邮寄",
    post_price: float = 0,
    can_self_pickup: bool = True,
) -> dict[str, Any]:
    session = Session.load()

    # 1. 上传图片（每张独立限流）
    image_infos: list[dict[str, Any]] = []
    for img_path in images:
        with acquire("item.write"):
            r = upload(img_path)
        image_infos.append({"url": r["url"], "width": r["width"], "height": r["height"]})

    # 2. AI 类目
    cat = recommend(title, json.dumps(image_infos))

    # 3. 默认地址
    loc = get_default_location()

    # 4. 发布（最后一步，走熔断）
    data = _build_publish_data(
        title=title,
        desc=desc,
        image_infos=image_infos,
        price=price,
        original_price=original_price,
        delivery=delivery,
        post_price=post_price,
        can_self_pickup=can_self_pickup,
        cat_info=cat,
        location=loc,
    )

    with acquire("item.write"), watch():
        raw = call(
            session,
            api="mtop.idle.pc.idleitem.publish",
            data=data,
            version="1.0",
            spm_cnt="a21ybx.publish.0.0",
        )

    data_out = raw.get("data", {}) or {}
    return {
        "item_id": data_out.get("itemId", ""),
        "title": title,
        "price": price,
        "cat_name": cat["cat_name"],
        "ok": any("SUCCESS" in r for r in raw.get("ret", [])),
    }


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
            "major": True,
            "type": 0,
            "status": "done",
        }
        for img in image_infos
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
        post_fee["postPriceInCent"] = str(int(post_price * 100))
        post_fee["templateId"] = "0"
    elif delivery == "无需邮寄":
        post_fee["templateId"] = "0"

    price_dto: dict[str, str] = {}
    default_price = price <= 0
    if not default_price:
        price_dto["priceInCent"] = str(int(price * 100))
    if original_price and original_price > 0:
        price_dto["origPriceInCent"] = str(int(original_price * 100))

    item_addr: dict[str, Any] = {}
    if location.get("division_id"):
        all_addrs = location.get("all", []) or []
        first = all_addrs[0] if all_addrs else {}
        item_addr = {
            "area": first.get("area", ""),
            "city": first.get("city", ""),
            "divisionId": first.get("divisionId", ""),
            "gps": f"{first.get('longitude', '')},{first.get('latitude', '')}",
            "poiId": first.get("poiId", ""),
            "poiName": first.get("poi", ""),
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
        "uniqueCode": "1775897582791680",
        "sourceId": "pcMainPublish",
        "bizcode": "pcMainPublish",
        "publishScene": "pcMainPublish",
    }
