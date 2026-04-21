"""auth login — 导入 cookie 到 ~/.goofish-cli/cookies.json。

支持两种格式：
- Chrome 扩展导出的 JSON 数组 [{"name":"...","value":"..."}]
- cookie 字符串 "k=v; k=v"（--raw）
"""

import json
from pathlib import Path

from goofish_cli.core import Strategy, command
from goofish_cli.core.session import DEFAULT_COOKIE_PATH


@command(
    namespace="auth",
    name="login",
    description="从 JSON 文件或 cookie 字符串导入登录态",
    strategy=Strategy.PUBLIC,
    columns=["path", "unb", "tracknick", "cookies_count"],
)
def login(source: str, *, raw: bool = False) -> dict[str, object]:
    if raw:
        cookies = _parse_raw(source)
    else:
        p = Path(source).expanduser()
        cookies = _parse_json(p.read_text())

    if "unb" not in cookies or "_m_h5_tk" not in cookies:
        raise ValueError("cookie 缺失关键字段 unb / _m_h5_tk，请重新从浏览器导出")

    target = DEFAULT_COOKIE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(
        [{"name": k, "value": v} for k, v in cookies.items()],
        ensure_ascii=False,
        indent=2,
    ))
    target.chmod(0o600)

    return {
        "path": str(target),
        "unb": cookies.get("unb", ""),
        "tracknick": cookies.get("tracknick", ""),
        "cookies_count": len(cookies),
    }


def _parse_raw(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, _, v = part.partition("=")
        out[k.strip()] = v.strip()
    return out


def _parse_json(text: str) -> dict[str, str]:
    data = json.loads(text)
    if isinstance(data, list):
        return {c["name"]: c["value"] for c in data if "name" in c and "value" in c}
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    raise ValueError("cookie JSON 格式不识别（需 list 或 dict）")
