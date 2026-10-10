"""从 PyPI 安装精确版本，核对工件哈希并验证真实 CLI/MCP，不使用账号凭证。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import timedelta
from pathlib import Path


async def handshake(version: str) -> int:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    args = ["--refresh-package", "goofish-cli", "--default-index", "https://pypi.org/simple",
            "--from", f"goofish-cli=={version}"]
    result = subprocess.run(["uvx", *args, "goofish", "version"], check=True,
                            capture_output=True, text=True, timeout=180)
    if result.stdout.strip() != f"goofish-cli {version}":
        raise ValueError("PyPI 安装后的 CLI 版本不一致")
    params = StdioServerParameters(command="uvx", args=[*args, "goofish-cli"], env=os.environ.copy())
    async with stdio_client(params) as (reader, writer), ClientSession(
        reader, writer, read_timeout_seconds=timedelta(seconds=90)
    ) as client:
        await client.initialize()
        tools = (await client.list_tools()).tools
        names = {tool.name for tool in tools}
        if not {"auth_status", "item_get", "item_publish", "search_items", "message_history"} <= names:
            raise ValueError("MCP 缺少核心工具")
        return len(tools)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--existing-only", action="store_true")
    args = parser.parse_args()
    artifacts = [p for p in args.dist.iterdir() if p.name.endswith((".whl", ".tar.gz"))]
    if len(artifacts) != 2:
        raise ValueError("必须验证同一次构建的 wheel 和 sdist")
    for attempt in range(1, 6):
        try:
            try:
                with urllib.request.urlopen(f"https://pypi.org/pypi/goofish-cli/{args.version}/json", timeout=20) as response:
                    data = json.load(response)
            except urllib.error.HTTPError as exc:
                if args.existing_only and exc.code == 404:
                    print("New PyPI version; no existing artifacts")
                    return
                raise
            files = {value["filename"]: value for value in data["urls"]}
            for artifact in artifacts:
                if args.existing_only and artifact.name not in files:
                    continue
                remote = files[artifact.name]
                if remote.get("yanked") or remote["digests"]["sha256"] != hashlib.sha256(artifact.read_bytes()).hexdigest():
                    raise ValueError("PyPI 工件与通过检查的构建产物不一致")
            if set(files) - {p.name for p in artifacts}:
                raise ValueError("PyPI 存在构建范围外的工件")
            if args.existing_only:
                print("Existing PyPI artifact hashes match checked build")
                return
            count = asyncio.run(handshake(args.version))
            print(json.dumps({"version": args.version, "artifact_hashes_match": True,
                              "cli_version_verified": True, "mcp_handshake": True,
                              "tool_count": count}))
            return
        except ValueError:
            raise
        except Exception as exc:
            if attempt == 5:
                raise
            print(f"PyPI validation attempt {attempt} pending: {type(exc).__name__}", flush=True)
            time.sleep(15)


if __name__ == "__main__":
    main()
