"""版本分支可跳过重复 CI，但 main 提交不能携带跳过标记。"""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "release_candidate", Path(__file__).resolve().parents[1] / "scripts/release_candidate.py"
)
release_candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_candidate)


@pytest.mark.parametrize("suffix", ["", " [skip ci]"])
def test_release_merge_subject_keeps_ci_enabled(suffix):
    assert release_candidate.merge_subject("chore(main): release 0.6.3" + suffix) == (
        "chore(main): release 0.6.3"
    )


@pytest.mark.parametrize(
    "title",
    [
        "chore(main): release 0.6.3 [skip actions]",
        "chore(main): release 0.6.3\n[skip ci]",
        "chore(main): release 0.6.3-rc.1 [skip ci]",
        "chore(main): release 0.6.3 [skip ci] [skip ci]",
    ],
)
def test_unexpected_release_subject_is_rejected(title):
    with pytest.raises(ValueError, match="标题"):
        release_candidate.merge_subject(title)
