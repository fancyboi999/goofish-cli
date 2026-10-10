"""只为本仓库机器人生成的发布 PR 输出候选，验证 SHA 后再合并。"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess


def gh(*args: str):
    return json.loads(subprocess.check_output(["gh", *args], text=True))


def output(**values) -> None:
    with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
        for key, value in values.items():
            stream.write(f"{key}={value}\n")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pull(number: int):
    repo = os.environ["GITHUB_REPOSITORY"]
    pr = gh("api", f"repos/{repo}/pulls/{number}")
    require(pr["user"]["login"] == "github-actions[bot]", "发布 PR 必须由 Actions 生成")
    require(pr["base"]["ref"] == "main" and pr["head"]["repo"]["full_name"] == repo, "错误的仓库或基线")
    require(pr["head"]["ref"].startswith("release-please--"), "错误的发布分支")
    require("autorelease: pending" in {x["name"] for x in pr["labels"]}, "缺少发布标记")
    require(bool(re.fullmatch(r"[0-9a-f]{40}", pr["head"]["sha"])), "无效的候选 SHA")
    return pr


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "merge"])
    args = parser.parse_args()
    if args.mode == "prepare":
        data = json.loads(os.environ["RELEASE_PR"])
        pr = pull(int(data["number"]))
        require(pr["state"] == "open" and not pr["draft"], "候选不是可合并发布 PR")
        require(pr["title"] == data["title"] and pr["head"]["ref"] == data["headBranchName"], "候选与发布程序输出不一致")
        versions = re.findall(r"\b\d+\.\d+\.\d+\b", data["title"])
        require(len(versions) == 1, "发布标题必须包含唯一版本")
        output(number=pr["number"], sha=pr["head"]["sha"], base=pr["base"]["sha"], version=versions[0])
        return
    number = int(os.environ["RELEASE_PR_NUMBER"])
    expected = os.environ["RELEASE_PR_SHA"]
    base = os.environ["RELEASE_BASE_SHA"]
    pr = pull(number)
    require(pr["head"]["sha"] == expected, "候选已更新，须重新验证")
    repo = os.environ["GITHUB_REPOSITORY"]
    current = gh("api", f"repos/{repo}/git/ref/heads/main")["object"]["sha"]
    require(current == base, "main 已更新，须重新生成发布 PR")
    subprocess.run(["gh", "pr", "merge", str(number), "--repo", repo,
                    "--squash", "--match-head-commit", expected], check=True)
    print(f"Validated release PR #{number} merged")


if __name__ == "__main__":
    main()
