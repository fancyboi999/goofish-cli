"""`_send()` 编排层的业务边界（不连真实 WebSocket）。

覆盖 reviewer 指出的路径：ready 超时、发送 ack 400、ack 超时、断连、
create-chat ack 失败，以及握手回包（/reg 非 200、ackDiff 400）。

FakeWS 用一个 responder 模拟服务端：按客户端发出的帧决定回什么，因此
`register()` / `wait_ready()` / `recv_ack()` 都跑的是真实实现，只有 socket
是假的。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from contextlib import asynccontextmanager

import pytest

from goofish_cli.commands.message import send as send_mod
from goofish_cli.core.errors import GoofishError

SEND_LWP = "/r/MessageSend/sendByReceiverScope"
CREATE_LWP = "/r/SingleChatConversation/create"


class FakeSession:
    unb = "user-1"
    device_id = "device-1"


class FakeWS:
    """按脚本应答的假 ws。空信箱时永久阻塞，让上层 timeout 生效。"""

    def __init__(self, responder, *, fail_recv_after: int | None = None):
        self.sent: list[dict] = []
        self._inbox: deque[dict] = deque()
        self._responder = responder
        self._fail_recv_after = fail_recv_after
        self._recv_count = 0

    async def send(self, raw: str) -> None:
        frame = json.loads(raw)
        self.sent.append(frame)
        for reply in self._responder(frame):
            self._inbox.append(reply)

    async def recv(self) -> str:
        self._recv_count += 1
        if self._fail_recv_after is not None and self._recv_count > self._fail_recv_after:
            raise ConnectionResetError("connection lost")
        if not self._inbox:
            await asyncio.sleep(3600)  # 没有下行：让 wait_for 超时
        return json.dumps(self._inbox.popleft())

    def lwps(self) -> list[str]:
        return [f.get("lwp") for f in self.sent]


def _mid(frame: dict) -> str:
    return (frame.get("headers") or {}).get("mid", "")


def make_responder(
    *,
    reg_code: int = 200,
    ack_diff_code: int = 400,  # 实测恒为 400，故设为默认
    push_vulcan: bool = True,
    send_code: int | None = 200,
    create_code: int | None = 200,
    message_id: str = "srv-1",
):
    def responder(frame: dict) -> list[dict]:
        lwp = frame.get("lwp")
        mid = _mid(frame)
        if lwp == "/reg":
            out = [{"headers": {"mid": mid}, "code": reg_code}]
            if push_vulcan:
                out.append({"headers": {"mid": "p-sync"}, "lwp": "/s/sync"})
                out.append({"headers": {"mid": "p-vulcan"}, "lwp": "/s/vulcan"})
            return out
        if lwp == "/r/SyncStatus/ackDiff":
            return [{"headers": {"mid": mid}, "code": ack_diff_code}]
        if lwp == CREATE_LWP:
            return [] if create_code is None else [{"headers": {"mid": mid}, "code": create_code}]
        if lwp == SEND_LWP:
            if send_code is None:
                return []
            return [{
                "headers": {"mid": mid},
                "code": send_code,
                "body": {"messageId": message_id, "receiverCount": 2},
            }]
        return []

    return responder


@pytest.fixture
def patched(monkeypatch):
    """把 connect / token / heartbeat 换掉，其余走真实实现。"""

    def _apply(ws: FakeWS):
        @asynccontextmanager
        async def fake_connect(_session):
            yield ws

        async def noop(*_a, **_k):
            await asyncio.sleep(3600)

        monkeypatch.setattr(send_mod, "connect", fake_connect)
        monkeypatch.setattr(send_mod, "get_access_token", lambda _s: "token-1")
        monkeypatch.setattr(send_mod, "heartbeat_loop", noop)
        return ws

    return _apply


def run_send(**kwargs):
    params = {
        "cid": "cid-1", "toid": "peer-1", "text": "hi", "kind": "text",
        "image_url": "", "image_width": 0, "image_height": 0, "item_id": "",
    }
    params.update(kwargs)
    return asyncio.run(send_mod._send(FakeSession(), **params))


class TestHappyPath:
    def test_waits_for_vulcan_before_sending(self, patched):
        ws = patched(FakeWS(make_responder()))
        out = run_send()
        assert out["ok"] is True
        assert out["message_id"] == "srv-1"
        # 发送必须排在 /reg 与 ackDiff 之后
        order = ws.lwps()
        assert order.index(SEND_LWP) > order.index("/reg")
        assert order.index(SEND_LWP) > order.index("/r/SyncStatus/ackDiff")

    def test_downstream_frames_are_acked(self, patched):
        ws = patched(FakeWS(make_responder()))
        run_send()
        # /s/sync 与 /s/vulcan 都要回 ack（code=200 的裸帧，无 lwp）
        acks = [f for f in ws.sent if f.get("code") == 200 and "lwp" not in f]
        assert len(acks) >= 2

    def test_ack_diff_400_is_not_fatal(self, patched):
        """实测 ackDiff 恒返回 400，且不影响发送。"""
        patched(FakeWS(make_responder(ack_diff_code=400)))
        assert run_send()["ok"] is True


class TestHandshakeFailures:
    def test_reg_non_200_aborts_before_sending(self, patched):
        ws = patched(FakeWS(make_responder(reg_code=401, push_vulcan=False)))
        with pytest.raises(GoofishError, match="IM 注册失败"):
            run_send()
        assert SEND_LWP not in ws.lwps()

    def test_no_vulcan_times_out_and_sends_nothing(self, patched, monkeypatch):
        monkeypatch.setattr(send_mod, "wait_ready", _short_wait_ready)
        ws = patched(FakeWS(make_responder(push_vulcan=False)))
        with pytest.raises(GoofishError, match="未就绪"):
            run_send()
        assert SEND_LWP not in ws.lwps()


class TestSendAckFailures:
    def test_ack_400_raises_and_does_not_report_success(self, patched):
        patched(FakeWS(make_responder(send_code=400)))
        with pytest.raises(GoofishError, match="ack_code=400"):
            run_send()

    def test_missing_ack_raises_timeout(self, patched, monkeypatch):
        monkeypatch.setattr(send_mod, "recv_ack", _short_recv_ack)
        patched(FakeWS(make_responder(send_code=None)))
        with pytest.raises(GoofishError, match="无回包"):
            run_send()

    def test_disconnect_mid_flight_propagates(self, patched):
        patched(FakeWS(make_responder(), fail_recv_after=2))
        with pytest.raises((ConnectionResetError, GoofishError)):
            run_send()


class TestCreateChat:
    def test_item_id_creates_chat_before_sending(self, patched):
        ws = patched(FakeWS(make_responder()))
        run_send(item_id="item-1")
        order = ws.lwps()
        assert order.index(CREATE_LWP) < order.index(SEND_LWP)

    def test_create_chat_without_ack_still_attempts_send(self, patched, monkeypatch):
        """create-chat 没有回包时不应静默中止；发送仍要尝试并被校验。"""
        monkeypatch.setattr(send_mod, "recv_ack", _passthrough_short_recv_ack)
        ws = patched(FakeWS(make_responder(create_code=None)))
        run_send(item_id="item-1")
        assert SEND_LWP in ws.lwps()


# --- 把真实实现的超时压到测试可接受的量级 ---

async def _short_wait_ready(ws, *, mids=None, timeout=15.0):
    from goofish_cli.core.ws import wait_ready
    return await wait_ready(ws, mids=mids, timeout=0.3)


async def _short_recv_ack(ws, mid, *, timeout=10.0):
    from goofish_cli.core.ws import recv_ack
    return await recv_ack(ws, mid, timeout=0.3)


async def _passthrough_short_recv_ack(ws, mid, *, timeout=10.0):
    from goofish_cli.core.ws import recv_ack
    return await recv_ack(ws, mid, timeout=0.3)
