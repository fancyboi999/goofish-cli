"""auth status — 检查登录态是否有效。调用 mtop.taobao.idlemessage.pc.loginuser.get"""

from typing import Any

from goofish_cli.core import Session, Strategy, command
from goofish_cli.core.mtop import call


@command(
    namespace="auth",
    name="status",
    description="检查登录态是否有效，返回 unb / tracknick / 昵称",
    strategy=Strategy.COOKIE,
    columns=["unb", "tracknick", "nick", "valid"],
)
def status() -> dict[str, Any]:
    session = Session.load()
    try:
        raw = call(
            session,
            api="mtop.taobao.idlemessage.pc.loginuser.get",
            data={},
            version="1.0",
            spm_cnt="a21ybx.im.0.0",
        )
        user = raw.get("data", {}) or {}
        return {
            "unb": session.unb,
            "tracknick": session.tracknick,
            "nick": user.get("nick", ""),
            "valid": True,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "unb": session.unb,
            "tracknick": session.tracknick,
            "nick": "",
            "valid": False,
            "error": str(e),
        }
