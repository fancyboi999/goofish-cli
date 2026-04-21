"""批量发布：一个目录 = 一个商品。

目录结构：
    listings/
      item-001/
        meta.json      -> {"title": "...", "desc": "...", "price": 999}
        1.png
        2.png
      item-002/
        ...

meta.json 里的 price 单位是元。脚本按目录顺序串行发，每条之间等 65 秒
（留足令牌桶的 1 写/分钟风控余量）。

跑法：
    python examples/publish_from_folder.py listings/

先用 `goofish auth login <cookies.json>` 导入登录态。
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path


def publish_one(folder: Path) -> None:
    meta_path = folder / "meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{folder} 缺 meta.json")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    images = sorted(p for p in folder.glob("*.png")) + sorted(folder.glob("*.jpg"))
    if not images:
        raise FileNotFoundError(f"{folder} 没有图片")

    cmd = [
        "goofish", "item", "publish",
        "--title", meta["title"],
        "--desc", meta["desc"],
        "--price", str(meta["price"]),
        "--images", ",".join(str(p) for p in images),
        "--format", "json",
    ]
    print(f"[pub] {folder.name} → {meta['title']}")
    out = subprocess.check_output(cmd)
    print(out.decode(), end="")


def main() -> None:
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)

    root = Path(sys.argv[1])
    folders = sorted(p for p in root.iterdir() if p.is_dir())
    if not folders:
        print(f"{root} 下没有子目录"); sys.exit(1)

    for i, folder in enumerate(folders):
        if i > 0:
            time.sleep(65)  # 令牌桶 1 写/分钟 + 缓冲
        publish_one(folder)


if __name__ == "__main__":
    main()
