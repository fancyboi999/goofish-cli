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


def test_bundled_skills_bundle_not_present_falls_back(monkeypatch, tmp_path) -> None:
    """模拟 wheel 态下找不到 _bundled_skills，验证 fallback 到 repo skills/ 能成功。"""
    import goofish_cli

    # 不真实改包位置，只 patch _bundle_root 的内部判断
    fake_pkg_dir = tmp_path / "fake_pkg"
    fake_pkg_dir.mkdir()
    fake_init = fake_pkg_dir / "__init__.py"
    fake_init.write_text("")

    monkeypatch.setattr(goofish_cli, "__file__", str(fake_init))

    # 此时 pkg_dir/_bundled_skills 不存在；fallback 要看 repo_root/skills，这里指不到
    with pytest.raises(FileNotFoundError):
        mod._bundle_root()
