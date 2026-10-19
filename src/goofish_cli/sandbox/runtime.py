"""沙箱浏览器常驻进程：调试接口只监听容器自己的 loopback。"""

from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright


def main() -> None:
    profile = Path.home() / ".goofish-cli" / "desktop-profile"
    profile.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    os.execv(
        executable,
        [
            executable,
            "--no-sandbox",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--lang=zh-CN",
            "--window-size=1440,1000",
            "about:blank",
        ],
    )


if __name__ == "__main__":
    main()
