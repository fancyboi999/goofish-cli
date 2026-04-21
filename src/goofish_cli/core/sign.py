"""execjs 桥接 goofish_js_version_2.js。提供 sign/device_id/mid/uuid/decrypt。"""
from __future__ import annotations

import subprocess
from functools import lru_cache, partial
from importlib.resources import files

# 静默 Windows 编码问题（跨平台无害）
subprocess.Popen = partial(subprocess.Popen, encoding="utf-8")

import execjs  # noqa: E402  必须在 subprocess 补丁之后


@lru_cache(maxsize=1)
def _ctx() -> execjs._abstract_runtime.AbstractRuntimeContext:
    js_path = files("goofish_cli.static").joinpath("goofish_js_version_2.js")
    return execjs.compile(js_path.read_text(encoding="utf-8"))


def generate_sign(t: str, token: str, data: str) -> str:
    return _ctx().call("generate_sign", t, token, data)


def generate_device_id(user_id: str) -> str:
    return _ctx().call("generate_device_id", user_id)


def generate_mid() -> str:
    return _ctx().call("generate_mid")


def generate_uuid() -> str:
    return _ctx().call("generate_uuid")


def decrypt(data: str) -> str:
    return _ctx().call("decrypt", data)
