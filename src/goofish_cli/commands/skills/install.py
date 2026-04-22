"""skills install — 把 goofish-cli 内置的 Claude Skills 复制到用户侧目录。

用法：
  goofish skills install                → 装到 ~/.claude/skills/
  goofish skills install --dest ./foo   → 装到指定目录
  goofish skills install --list         → 仅列出内置 skill，不拷贝
  goofish skills install --force        → 覆盖已存在的 skill 目录

skills 打包方式：pyproject.toml 里 hatch force-include 把项目根 `skills/` 收进
wheel 的 `goofish_cli/_bundled_skills/` 下；运行时用 `goofish_cli.__file__` 拿
包路径再拼 `_bundled_skills` 就能定位到它（不依赖 importlib.resources 对 namespace
package 的识别，避免 py 版本差异坑）。
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import goofish_cli
from goofish_cli.core import Strategy, command


def _bundle_root() -> Path:
    """wheel 态：site-packages/goofish_cli/_bundled_skills；dev 态：repo/skills。"""
    pkg_dir = Path(goofish_cli.__file__).resolve().parent
    bundled = pkg_dir / "_bundled_skills"
    if bundled.is_dir():
        return bundled
    # dev 回退：从 src/goofish_cli/ 爬到仓库根
    repo_root = pkg_dir.parent.parent
    dev_path = repo_root / "skills"
    if dev_path.is_dir():
        return dev_path
    raise FileNotFoundError(
        "找不到打包的 skills 资源。请确认已通过 pip / uvx 安装 goofish-cli，"
        "或在仓库根目录执行（dev 态）。"
    )


def _default_dest() -> Path:
    return Path.home() / ".claude" / "skills"


@command(
    namespace="skills",
    name="install",
    description="把内置 Claude Skills 复制到 ~/.claude/skills/（或 --dest 指定目录）",
    strategy=Strategy.PUBLIC,
    columns=["skill", "status", "path"],
)
def install(
    dest: str | None = None,
    force: bool = False,
    list: bool = False,  # noqa: A002
) -> list[dict[str, Any]]:
    root = _bundle_root()
    skill_dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())

    if list:
        return [
            {"skill": d.name, "status": "available", "path": str(d)}
            for d in skill_dirs
        ]

    target = Path(dest).expanduser() if dest else _default_dest()
    target.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for src in skill_dirs:
        dst = target / src.name
        if dst.exists():
            if not force:
                results.append({"skill": src.name, "status": "skipped (exists)", "path": str(dst)})
                continue
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        results.append({"skill": src.name, "status": "installed", "path": str(dst)})

    return results
