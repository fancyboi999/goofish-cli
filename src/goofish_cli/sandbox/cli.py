"""在独立 Docker 桌面内启动、登录和执行 CLI/MCP。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from importlib.metadata import distribution, requires
from pathlib import Path
from typing import Annotated
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import typer

import goofish_cli

app = typer.Typer(
    help="独立 Docker 桌面：登录、CLI 和 MCP 均不占用本机桌面。", no_args_is_help=True
)
CONTAINER = "goofish-sandbox"
VOLUME = "goofish-sandbox-state"
OWNER = "io.goofish-cli.desktop-sandbox"
ASSETS = Path(__file__).parent / "assets"


def _fail(message: str, code: int = 1) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code)


def _docker(*args: str, capture: bool = False, check: bool = True, stream_errors: bool = False):
    try:
        result = subprocess.run(
            ["docker", *args],
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture and not stream_errors else None,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        _fail("找不到 Docker。请先安装并启动 Docker Desktop，或本机 Docker Engine。")
    if check and result.returncode:
        if capture and result.stderr:
            typer.echo(result.stderr.strip(), err=True)
        _fail("Docker 操作失败；不会回退到本机浏览器。")
    return result


def _inspect(kind: str, name: str):
    result = _docker(kind, "inspect", name, capture=True, check=False)
    if result.returncode:
        if "no such" in result.stderr.lower():
            return None
        _fail("无法访问 Docker。请确认本机 Docker 服务已启动。")
    return json.loads(result.stdout)[0]


def _container():
    info = _inspect("container", CONTAINER)
    if info and (info["Config"].get("Labels") or {}).get(OWNER) != "true":
        _fail(f"已有同名容器 {CONTAINER} 不属于 goofish；未修改它。")
    return info


def _require_running():
    info = _container()
    if not info or not info["State"]["Running"]:
        _fail("沙箱未运行。请先执行 goofish sandbox start。")
    _viewer(info)
    return info


def _viewer(info) -> str:
    ports = info["HostConfig"]["PortBindings"].get("6080/tcp") or []
    if len(ports) != 1 or ports[0].get("HostIp") != "127.0.0.1":
        _fail("沙箱观察端口必须只绑定 127.0.0.1；请停止并重建沙箱。")
    return f"http://127.0.0.1:{ports[0]['HostPort']}/vnc.html?autoconnect=1&resize=scale"


def _host_only() -> None:
    if os.environ.get("GOOFISH_DESKTOP_SANDBOX") == "1":
        _fail("请在宿主机执行 sandbox 管理命令；容器内直接执行普通业务命令。")


def _build_context(destination: Path) -> str:
    package = Path(goofish_cli.__file__).resolve().parent
    target = destination / "package" / "goofish_cli"
    shutil.copytree(package, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # wheel 自带 skills；editable 安装通过现有入口找到仓库的 skills。
    from goofish_cli.commands.skills.install import _bundle_root

    if not (target / "_bundled_skills").exists():
        shutil.copytree(_bundle_root(), target / "_bundled_skills")
    dependencies = requires("goofish-cli") or []
    (destination / "requirements.txt").write_text("\n".join(dependencies) + "\n")
    installed = distribution("goofish-cli")
    for path in installed.files or []:
        if path.name in {"LICENSE", "NOTICE"}:
            shutil.copyfile(installed.locate_file(path), destination / "package" / path.name)
    project = (
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n'
        '[project]\nname = "goofish-cli"\n'
        f'version = {json.dumps(goofish_cli.__version__)}\nrequires-python = ">=3.11"\n'
        f"dependencies = {json.dumps(dependencies)}\n"
        '[project.scripts]\ngoofish = "goofish_cli.cli:app"\n'
        'goofish-cli = "goofish_cli.mcp_server:main"\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["goofish_cli"]\n'
    )
    (destination / "package" / "pyproject.toml").write_text(project)
    for name in ("Dockerfile", "entrypoint.sh"):
        shutil.copyfile(ASSETS / name, destination / name)
    digest = hashlib.sha256()
    for path in sorted(destination.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(destination)).encode())
            digest.update(path.read_bytes())
    return f"goofish-cli-sandbox:{digest.hexdigest()[:16]}"


def _ready(info, timeout: float = 30) -> None:
    # localhost 观察链路不经过用户的代理配置。
    opener = build_opener(ProxyHandler({}))
    url = _viewer(info)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url, timeout=1) as response:
                if response.status == 200:
                    return
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.2)
    _fail("沙箱桌面尚未就绪。请检查 docker logs goofish-sandbox；不会启动本机浏览器。")


@app.command()
def start(
    port: Annotated[int, typer.Option(min=1024, max=65535, help="本机 noVNC 端口")] = 16080,
    rebuild: Annotated[bool, typer.Option(help="重建镜像和已停止容器，保留登录态卷")] = False,
):
    """启动虚拟桌面；首次构建镜像。只打印观察链接，不自动打开浏览器。"""
    _host_only()
    info = _container()
    if info:
        _viewer(info)
    if info and info["State"]["Running"]:
        if rebuild:
            _fail("请先执行 goofish sandbox stop，再使用 --rebuild。")
        _ready(info)
        typer.echo(_viewer(info))
        return
    if info and not rebuild:
        _docker("start", CONTAINER, capture=True)
    else:
        state = _inspect("volume", VOLUME)
        if state and (state.get("Labels") or {}).get(OWNER) != "true":
            _fail(f"已有同名卷 {VOLUME} 不属于 goofish；未修改它。")
        _docker("volume", "create", "--label", f"{OWNER}=true", VOLUME, capture=True)
        with tempfile.TemporaryDirectory(prefix="goofish-sandbox-build-") as directory:
            context = Path(directory)
            image = _build_context(context)
            if rebuild or not _inspect("image", image):
                # 构建日志属于 stderr，不污染命令的结构化输出。
                result = subprocess.run(
                    ["docker", "build", "--label", f"{OWNER}=true", "-t", image, str(context)],
                    stdout=subprocess.DEVNULL,
                    check=False,
                )
                if result.returncode:
                    _fail("沙箱镜像构建失败；没有启动本机浏览器。")
        if info:
            _docker("rm", CONTAINER, capture=True)
        _docker(
            "run",
            "-d",
            "--init",
            "--name",
            CONTAINER,
            "--hostname",
            CONTAINER,
            "--label",
            f"{OWNER}=true",
            "--cpus",
            "3",
            "--memory",
            "3g",
            "--shm-size",
            "1g",
            "--security-opt",
            "no-new-privileges",
            "-p",
            f"127.0.0.1:{port}:6080",
            "--mount",
            f"type=volume,source={VOLUME},target=/home/pwuser/.goofish-cli",
            image,
            capture=True,
        )
    info = _require_running()
    _ready(info)
    typer.echo(_viewer(info))


@app.command()
def status():
    """显示沙箱状态，不读取或输出账号凭证。"""
    _host_only()
    info = _container()
    typer.echo(
        json.dumps(
            {
                "running": bool(info and info["State"]["Running"]),
                "viewer": _viewer(info) if info else None,
                "state_volume": VOLUME,
            },
            ensure_ascii=False,
        )
    )


@app.command()
def stop():
    """停止虚拟桌面和其中的浏览器，保留登录态。"""
    _host_only()
    info = _container()
    if info and info["State"]["Running"]:
        _docker("stop", CONTAINER, capture=True)
    typer.echo("沙箱已停止；登录态卷保留。")


@app.command()
def login(timeout: Annotated[int, typer.Option(min=30, max=3600)] = 600):
    """在沙箱内扫码登录；用户通过观察链接操作，登录态不导回宿主机。"""
    _host_only()
    info = _require_running()
    _ready(info)
    typer.echo(f"请打开 {_viewer(info)}，用闲鱼 App 扫码并确认。", err=True)
    result = _docker(
        "exec",
        CONTAINER,
        "goofish",
        "auth",
        "login",
        "--qr",
        "--qr-timeout",
        str(timeout),
        "--format",
        "json",
        capture=True,
        check=False,
        stream_errors=True,
    )
    if result.returncode:
        _fail("沙箱扫码登录未完成；可重新执行 goofish sandbox login。", result.returncode)
    checked = _docker(
        "exec",
        CONTAINER,
        "goofish",
        "auth",
        "status",
        "--format",
        "json",
        capture=True,
        check=False,
    )
    try:
        valid = checked.returncode == 0 and json.loads(checked.stdout).get("valid") is True
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        _fail("扫码数据已保存到沙箱，但账号接口尚未确认有效；请在沙箱内检查登录。", 77)
    typer.echo("沙箱登录成功，账号接口已确认有效；登录态保存在独立 Docker 卷。")


@app.command(
    context_settings={
        "allow_extra_args": True,
        "ignore_unknown_options": True,
        "help_option_names": [],
    }
)
def run(ctx: typer.Context):
    """执行普通 goofish 命令，例如 sandbox run search items 机械键盘 --limit 3。"""
    _host_only()
    _require_running()
    if not ctx.args or ctx.args[0] == "sandbox":
        _fail("请提供普通业务命令，例如 goofish sandbox run auth status。", 2)
    result = _docker("exec", "-i", CONTAINER, "goofish", *ctx.args, check=False)
    raise typer.Exit(result.returncode)


@app.command()
def mcp():
    """通过 stdio 连接沙箱内 MCP server；客户端使用 goofish sandbox mcp。"""
    _host_only()
    if sys.stdin.isatty():
        _fail("MCP 是 stdio 服务；请在 MCP 客户端中配置 goofish sandbox mcp。", 2)
    _require_running()
    result = _docker("exec", "-i", CONTAINER, "goofish-cli", check=False)
    raise typer.Exit(result.returncode)
