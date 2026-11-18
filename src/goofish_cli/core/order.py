"""订单发货纯逻辑：秘钥池、内容模板、发货返回码分类、先标记后发内容决策。

移植自 xianyu-seller 技能 fulfill.py / fulfill_api.md 的确定性规则，
与网络/IM 层解耦，便于单测。

边界（硬性，与技能一致）：
- 顺序固定：先调 consign 标记已发货，**成功后才**生成并发送内容；
  API 失败绝不发内容，避免买家拿到内容但订单仍挂待发货。
- ORDER_ALREADY_DELIVERY 视为幂等成功，可继续发内容。
- TOKEN_EXPIRED 由调用层走 cookie 续期后重试一次；其他失败记报告等人工。

网络层（consign.dummy HTTP 调用、IM 会话系统卡片识别 orderId）依赖真实订单
样本验证 appKey/签名/消息体结构，见文件末尾 TODO，不在此模块写死未验证调用。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ── 发货返回码分类（mtop.taobao.idle.logistic.consign.dummy）──
def classify_consign_ret(ret: str) -> str:
    """把 mtop ret 串分类为：success / already_delivered / token_expired / failed。

    - SUCCESS::调用成功            → success
    - ORDER_ALREADY_DELIVERY       → already_delivered（幂等成功）
    - FAIL_SYS_TOKEN_EXPIRED / EXOIRED → token_expired（续期重试一次）
    - 其他 FAIL_SYS_* / ERROR     → failed（不发内容，人工处理）
    """
    text = ret or ""
    if "ORDER_ALREADY_DELIVERY" in text:
        return "already_delivered"
    if "SUCCESS" in text:
        return "success"
    if "TOKEN_EXPIRED" in text or "TOKEN_EXOIRED" in text:
        return "token_expired"
    return "failed"


def mark_succeeded(category: str) -> bool:
    """consign 标记是否可视为成功（含幂等已发货），决定能否进入发内容。"""
    return category in ("success", "already_delivered")


# ── 秘钥池：弹出第一行并原子写回（单进程串行由调用层锁保证）──
def pop_key(pool_file: Path) -> str | None:
    """弹出秘钥池第一行并写回；文件缺失/空返回 None。消耗不可逆。"""
    if not pool_file.exists():
        return None
    lines = [ln.strip() for ln in pool_file.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        return None
    key = lines.pop(0)
    pool_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return key


# ── 发货内容组装：fixed 固定文本 / key_pool 弹秘钥套模板 ──
def build_message(cfg: dict[str, Any], errors: list[str] | None = None) -> str | None:
    """按配置生成发货内容。失败时把原因追加到 errors，返回 None。

    cfg:
      mode: "fixed" | "key_pool"
      fixed_text: fixed 模式文本
      key_pool_file: 秘钥池文件路径
      message_template: key_pool 模板，{key} 占位（默认通用话术）
    """
    errors = errors if errors is not None else []
    mode = cfg.get("mode", "")
    if mode == "fixed":
        text = (cfg.get("fixed_text") or "").strip()
        if not text:
            errors.append("fixed 模式但 fixed_text 为空")
            return None
        return text
    if mode == "key_pool":
        pool = Path(cfg.get("key_pool_file", "")).expanduser()
        key = pop_key(pool)
        if not key:
            errors.append("秘钥池为空或文件不存在")
            return None
        tpl = cfg.get("message_template") or "您的秘钥：{key}，祝您使用愉快！"
        return tpl.format(key=key)
    errors.append(f"未知发货模式: {mode!r}（支持 fixed / key_pool）")
    return None


# ── 先标记后发内容的决策纯函数 ──
def delivery_step(mark_category: str, message: str | None) -> dict[str, Any]:
    """单步发货决策：返回动作分类与是否应发内容。

    返回:
      {
        "mark": category,
        "send_content": bool,      # 是否允许发内容
        "action": "deliver" | "retry_token" | "hold",
        "note": str,
      }
    """
    if mark_category == "token_expired":
        return {"mark": mark_category, "send_content": False,
                "action": "retry_token", "note": "token 过期，首页续期后重试一次"}
    if mark_succeeded(mark_category):
        if not message:
            return {"mark": mark_category, "send_content": False,
                    "action": "hold", "note": "标记成功但内容为空，订单已标记、内容未发"}
        return {"mark": mark_category, "send_content": True,
                "action": "deliver", "note": "标记成功，发送发货内容"}
    return {"mark": mark_category, "send_content": False,
            "action": "hold", "note": "API 标记失败，不发内容，记报告等人工"}


__test__ = {
    "classify_consign_ret": classify_consign_ret,
    "mark_succeeded": mark_succeeded,
    "pop_key": pop_key,
    "build_message": build_message,
    "delivery_step": delivery_step,
}
