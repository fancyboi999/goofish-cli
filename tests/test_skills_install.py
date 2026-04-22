"""测 goofish skills install 命令：list / copy / force / custom dest / missing bundle."""
from __future__ import annotations

from pathlib import Path

import pytest

from goofish_cli.commands.skills import install as mod


@pytest.fixture(autouse=True)
def _default_home(tmp_path, monkeypatch):
    # 防止真写到 ~/.claude/skills/
    monkeypatch.setenv("HOME", str(tmp_path))


def test_bundle_root_in_dev() -> None:
    """开发态（从仓库跑）应当回退到仓库根 skills/ 并找到至少 1 个 SKILL.md。"""
    root = mod._bundle_root()
    assert root.is_dir()
    skills = [p for p in root.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]
    assert len(skills) >= 5, f"预期 ≥5 个 skill，实际 {len(skills)}: {[s.name for s in skills]}"


def test_install_list_only_does_not_copy(tmp_path) -> None:
    out = mod.install(dest=str(tmp_path / "target"), list=True)

    # list 模式纯列举
    assert len(out) >= 5
    assert all(row["status"] == "available" for row in out)
    # 不应该创建目标目录
    assert not (tmp_path / "target").exists()


def test_install_copies_all_skills(tmp_path) -> None:
    dest = tmp_path / "target"
    out = mod.install(dest=str(dest), list=False)

    assert dest.is_dir()
    assert all(row["status"] == "installed" for row in out)

    # 每个 skill 至少有 SKILL.md
    for row in out:
        skill_dir = Path(row["path"])
        assert skill_dir.is_dir()
        assert (skill_dir / "SKILL.md").is_file()


def test_install_skips_existing_without_force(tmp_path) -> None:
    dest = tmp_path / "target"
    # 第一次装
    mod.install(dest=str(dest))

    # 改一个文件，再跑第二次不加 force
    first_skill = next(dest.iterdir())
    marker = first_skill / "MARK.txt"
    marker.write_text("preserved")

    out2 = mod.install(dest=str(dest))
    assert any("skipped" in row["status"] for row in out2)
    # marker 应当保留（说明没覆盖）
    assert marker.read_text() == "preserved"


def test_install_force_overwrites(tmp_path) -> None:
    dest = tmp_path / "target"
    mod.install(dest=str(dest))

    first_skill = next(dest.iterdir())
    (first_skill / "MARK.txt").write_text("will be gone")

    out = mod.install(dest=str(dest), force=True)
    assert all(row["status"] == "installed" for row in out)
    # --force 会先 rmtree 再 copytree → MARK.txt 应消失
    assert not (first_skill / "MARK.txt").exists()


def test_command_registered_in_registry() -> None:
    """通过 registry discover 能找到 skills.install 命令。"""
    from goofish_cli.core.registry import discover, registry

    discover()
    reg = registry()
    assert "skills.install" in reg
    cmd = reg["skills.install"]
    assert cmd.namespace == "skills"
    assert cmd.name == "install"


def test_bundled_skills_missing_and_fallback_unreachable_raises(monkeypatch, tmp_path) -> None:
    """wheel 态找不到 _bundled_skills 且 dev 态 repo skills/ 也不可达时，应抛 FileNotFoundError。"""
    import goofish_cli

    # 用假 pkg 路径骗 `_bundle_root`：pkg_dir 下没有 _bundled_skills，
    # pkg_dir.parent.parent 下也不会有 skills/ 目录 → 两条路径都失败 → FileNotFoundError
    fake_pkg_dir = tmp_path / "fake_pkg"
    fake_pkg_dir.mkdir()
    fake_init = fake_pkg_dir / "__init__.py"
    fake_init.write_text("")

    monkeypatch.setattr(goofish_cli, "__file__", str(fake_init))

    with pytest.raises(FileNotFoundError):
        mod._bundle_root()


def test_install_force_replaces_file_with_skill_dir(tmp_path) -> None:
    """--force 时如果目标位置是**文件**（或 symlink），不能用 rmtree；要 unlink 再 copytree。"""
    dest = tmp_path / "target"
    dest.mkdir()
    # 在目标位置创建一个同名文件（不是目录），模拟用户误操作
    stray = dest / "goofish-overview"
    stray.write_text("not a skill dir, just a file")

    out = mod.install(dest=str(dest), force=True)

    # 应该全部 installed，不应该报 NotADirectoryError
    assert all(row["status"] == "installed" for row in out)
    # 原文件应被替换为目录
    assert (dest / "goofish-overview").is_dir()
    assert (dest / "goofish-overview" / "SKILL.md").is_file()
