"""auth reset-guard — 手动解除风控熔断状态。"""

from goofish_cli.core import Strategy, command
from goofish_cli.core.guard import reset


@command(
    namespace="auth",
    name="reset-guard",
    description="手动解除风控熔断状态",
    strategy=Strategy.PUBLIC,
    columns=["ok"],
)
def reset_guard() -> dict[str, bool]:
    reset()
    return {"ok": True}
