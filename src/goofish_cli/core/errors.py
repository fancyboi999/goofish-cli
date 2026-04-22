"""统一异常体系。driver 层根据响应体 ret 或状态自动抛对应异常。

退出码参照 sysexits.h（与 opencli 对齐）：
- 1   GENERIC
- 75  TEMPFAIL   —— RateLimitedError
- 76  RISK       —— RiskControlError（项目特有，对应 RGV587 / punish）
- 77  NOPERM     —— AuthRequiredError
- 78  CONFIG     —— SignError
- 79  NOINPUT    —— NotFoundError / EmptyResultError / BlockedError
"""
from __future__ import annotations


class GoofishError(Exception):
    exit_code = 1

    def __init__(self, message: str, *, raw: dict | None = None, hint: str | None = None):
        super().__init__(message)
        self.raw = raw
        self.hint = hint


class AuthRequiredError(GoofishError):
    exit_code = 77


class SignError(GoofishError):
    exit_code = 78


class RateLimitedError(GoofishError):
    exit_code = 75


class RiskControlError(GoofishError):
    """触发风控：RGV587 / punish / FAIL_SYS_USER_VALIDATE 等。"""
    exit_code = 76


class NotFoundError(GoofishError):
    exit_code = 79


class EmptyResultError(GoofishError):
    """查询无命中。对标 opencli EmptyResultError。"""
    exit_code = 79


class BlockedError(GoofishError):
    """请求被拦截（验证码页 / 安全验证 / 异常访问）。对标 opencli 的 blocked 分支。"""
    exit_code = 79
