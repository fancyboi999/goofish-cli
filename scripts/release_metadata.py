"""核对版本契约，并限定自动发布 PR 只能更新版本、安装示例和发布说明。"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JSON_VERSIONS = (
    "package.json", ".codex-plugin/plugin.json", "openclaw.plugin.json",
    ".claude-plugin/marketplace.json",
)
DOCS = ("README.md", "docs/mcp-setup.md")
ALLOWED = {*JSON_VERSIONS, *DOCS, ".mcp.json", "pyproject.toml", "CHANGELOG.md",
           ".release-please-manifest.json"}
VERSION = re.compile(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def normalize(path: str, content: str, version: str):
    if path in JSON_VERSIONS:
        value = json.loads(content)
        value["version"] = "VERSION"
        return value
    if path == ".mcp.json":
        value = json.loads(content)
        value["mcpServers"]["goofish"]["args"][1] = "VERSION"
        return value
    if path == ".release-please-manifest.json":
        value = json.loads(content)
        value["."] = "VERSION"
        return value
    if path == "pyproject.toml":
        value = tomllib.loads(content)
        value["project"]["version"] = "VERSION"
        return value
    return content.replace("goofish-cli==" + version, "goofish-cli==VERSION")


def check(tag: str = "", base: str = "") -> str:
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if not VERSION.fullmatch(version):
        raise ValueError("发布版本必须是稳定 SemVer")
    if tag and tag != "v" + version:
        raise ValueError("tag 与构建版本不一致；只允许从对应版本 tag 发布")
    for path in JSON_VERSIONS:
        if json.loads((ROOT / path).read_text())["version"] != version:
            raise ValueError(f"版本不一致：{path}")
    args = json.loads((ROOT / ".mcp.json").read_text())["mcpServers"]["goofish"]["args"]
    if args != ["--from", "goofish-cli==" + version, "goofish-cli"]:
        raise ValueError("MCP 必须精确锁定本次 Python 版本")
    if json.loads((ROOT / ".release-please-manifest.json").read_text()) != {".": version}:
        raise ValueError("release-please manifest 与 Python 版本不一致")
    if not re.search(r"^## .*\b" + re.escape(version) + r"\b", (ROOT / "CHANGELOG.md").read_text(), re.M):
        raise ValueError("CHANGELOG 缺少本次发布说明")
    for path in DOCS:
        pins = re.findall(r"goofish-cli==(\d+\.\d+\.\d+)", (ROOT / path).read_text())
        if not pins or any(pin != version for pin in pins):
            raise ValueError(f"安装示例没有同步版本：{path}")
    if base:
        if not re.fullmatch(r"[0-9a-f]{40}", base):
            raise ValueError("基线必须是完整 commit SHA")
        changed = git("diff", "--name-only", base, "HEAD").splitlines()
        if not changed or set(changed) - ALLOWED:
            raise ValueError("自动发布 PR 包含版本文件范围外的改动")
        old_version = tomllib.loads(git("show", base + ":pyproject.toml"))["project"]["version"]
        if version == old_version:
            raise ValueError("自动发布 PR 没有更新版本")
        for path in changed:
            before = git("show", base + ":" + path)
            after = (ROOT / path).read_text().strip()
            mode = git("ls-tree", "HEAD", path).split()[0]
            if mode != "100644":
                raise ValueError(f"版本文件必须是普通不可执行文件：{path}")
            if path != "CHANGELOG.md" and normalize(path, before, old_version) != normalize(path, after, version):
                raise ValueError(f"自动发布 PR 修改了非版本内容：{path}")
    return version


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--tag", default="")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    try:
        print("Release metadata verified:", check(args.tag, args.base))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Release rejected: {exc}\n")


if __name__ == "__main__":
    main()
