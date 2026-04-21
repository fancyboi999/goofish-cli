"""统一异常体系。driver 层根据响应体 ret 或状态自动抛对应异常。"""
from __future__ import annotations


class GoofishError(Exception):
    exit_code = 1

    def __init__(self, message: str, *, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw


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
