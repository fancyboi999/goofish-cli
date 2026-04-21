"""location default — 获取默认发布地址。

接口：mtop.taobao.idle.local.poi.get v1.0
"""

from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call


@command(
    namespace="location",
    name="default",
    description="获取账号默认发布地址",
    strategy=Strategy.COOKIE,
    columns=["prov", "city", "area", "poi", "division_id"],
)
def default(longitude: float = 121.4737, latitude: float = 31.2304) -> dict[str, Any]:
    session = Session.load()
    raw = call(
        session,
        api="mtop.taobao.idle.local.poi.get",
        data={"longitude": longitude, "latitude": latitude},
        version="1.0",
        spm_cnt="a21ybx.publish.0.0",
    )
    data = raw.get("data", {}) or {}
    addrs = data.get("commonAddresses", []) or []
    selected = data.get("selectedPoi") or (addrs[0] if addrs else None)
    if not selected:
        return {"prov": "", "city": "", "area": "", "poi": "", "division_id": "", "all": []}
    return {
        "prov": selected.get("prov", ""),
        "city": selected.get("city", ""),
        "area": selected.get("area", ""),
        "poi": selected.get("poi", ""),
        "division_id": str(selected.get("divisionId", "")),
        "all": addrs or [selected],
    }
