"""item update — 修改在售商品价格（元，内部转分）。

流程：editDetail（读取编辑页全量）→ 回写差异字段（仅价格）→ edit
接口：mtop.idle.pc.idleitem.editDetail v1.0（只读）+ mtop.idle.pc.idleitem.edit v1.0（写操作）

为什么不做「全量重建」：editDetail 返回的是编辑页当前可编辑数据，
原样回传再覆写 itemPriceDTO.priceInCent，其余字段保持服务端当前值，
避免只改价时意外破坏标题/图片/类目/地址。
"""

import json
import time
from typing import Any

from goofish_cli.commands.item.publish import _money
from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.errors import GoofishError
from goofish_cli.core.mtop import call
from goofish_cli.core.write_operation import write_operation

# edit 提交需要的场景字段；editDetail 响应不含这些键，按 PC 编辑页行为补齐。
_SCENE_FIELDS = {
    "sourceId": "pcMainPublish",
    "bizcode": "pcMainPublish",
    "publishScene": "pcMainPublish",
}


@command(
    namespace="item",
    name="update",
    description="修改在售商品价格（价格单位元；先拉编辑详情再回写差异字段）",
    strategy=Strategy.COOKIE,
    columns=["item_id", "old_price", "new_price", "ok", "message"],
    write=True,
    arguments=["item_id"],
)
def update(item_id: str, *, price: float | None = None, dry_run: bool = False) -> dict[str, Any]:
    if price is None:
        raise GoofishError("必须提供 --price（单位元，最多两位小数）")
    if price <= 0:
        raise GoofishError("价格必须大于 0（单位元，最多两位小数）")
    cents = _money(price)
    if dry_run:
        # dry-run 不发任何请求：payload 只能展示「将覆写的差异字段」，
        # 全量回写体在真实执行时由 editDetail 的当前返回决定。
        return {
            "item_id": str(item_id),
            "new_price": price,
            "priceInCent": cents,
            "dry_run": True,
            "would_overwrite": {"itemPriceDTO": {"priceInCent": cents}},
            "ok": None,
            "message": "dry-run：未发送任何请求",
        }
    session = Session.load()
    detail_raw = call(
        session,
        api="mtop.idle.pc.idleitem.editDetail",
        data={"itemId": str(item_id)},
        version="1.0",
        spm_cnt="a21ybx.item.0.0",
    )
    detail = detail_raw.get("data") if isinstance(detail_raw, dict) else None
    if not isinstance(detail, dict) or not detail:
        raise GoofishError("editDetail 返回为空，无法构造编辑 payload")
    payload = _build_edit_payload(detail, item_id=str(item_id), price_cents=cents)
    with write_operation(session, "item.write"):
        raw = call(
            session,
            api="mtop.idle.pc.idleitem.edit",
            data=payload,
            version="1.0",
            spm_cnt="a21ybx.publish.0.0",
        )
    ret = raw.get("ret") or []
    joined = " | ".join(ret)
    if "LEAD_ITEM_NOT_SUPPORT_CURRENT_EDIT_PATH" in joined:
        # 平台限制：线索宝贝（服务类目）禁止 PC 编辑链路，仅 APP 可编辑。
        raise GoofishError("该商品是线索宝贝（服务类目），闲鱼网页端不支持编辑/改价；"
                           "请在闲鱼 App 内修改，或下架后重新发布。原始错误：" + joined)
    old_cents = str((detail.get("itemPriceDTO") or {}).get("priceInCent", ""))
    return {
        "item_id": str(item_id),
        "old_price": int(old_cents) / 100 if old_cents.isdigit() else old_cents,
        "new_price": price,
        "priceInCent": cents,
        "ok": any("SUCCESS" in r for r in ret),
        "message": joined,
    }


def _build_edit_payload(detail: dict[str, Any], *, item_id: str, price_cents: str) -> dict[str, Any]:
    """从 editDetail 全量构造 edit 请求体：除价格外逐字段保持原值。"""
    data = json.loads(json.dumps(detail))
    data["itemId"] = str(item_id)
    price_dto = dict(data.get("itemPriceDTO") or {})
    price_dto["priceInCent"] = str(price_cents)
    data["itemPriceDTO"] = price_dto
    data.setdefault("simpleItem", "true")
    data.setdefault("uniqueCode", str(time.time_ns() // 1000))
    data.update(_SCENE_FIELDS)
    return data
