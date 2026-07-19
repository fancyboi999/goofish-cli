from types import SimpleNamespace

import pytest

from goofish_cli import mcp_server


def test_main_rejects_interactive_terminal(monkeypatch, capsys):
    monkeypatch.setattr(mcp_server.sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(mcp_server, "_register_all", lambda: pytest.fail("registered tools"))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: pytest.fail("started MCP server"))

    with pytest.raises(SystemExit) as exc_info:
        mcp_server.main()

    assert exc_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "MCP stdio server" in stderr
    assert "goofish --help" in stderr


def test_main_starts_mcp_server_for_piped_stdin(monkeypatch):
    calls = []
    monkeypatch.setattr(mcp_server.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(mcp_server, "_register_all", lambda: calls.append("register"))
    monkeypatch.setattr(mcp_server.mcp, "run", lambda: calls.append("run"))

    mcp_server.main()

    assert calls == ["register", "run"]


def test_all_commands_register_as_mcp_tools():
    mcp_server._register_all()
