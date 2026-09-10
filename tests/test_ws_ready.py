"""wait_ready / recv_ack 的时序逻辑（不连 WebSocket）。

背景：`/r/` 请求在服务端推 `/s/vulcan` 之前发出会被以 `code 400` 拒绝，
而 `/reg` 自身返回 200，容易误判连接已就绪。
"""

import asyncio
import json

import pytest

from goofish_cli.core.ws import recv_ack, wait_ready


class FakeWS:
    """按脚本吐帧的假 ws；记录本端发出的内容。"""

    def __init__(self, frames: list[dict]):
        self._frames = list(frames)
        self.sent: list[dict] = []

    async def recv(self) -> str:
        if not self._frames:
            await asyncio.sleep(3600)  # 模拟没有更多下行
        return json.dumps(self._frames.pop(0))

    async def send(self, raw: str) -> None:
        self.sent.append(json.loads(raw))


def test_wait_ready_returns_on_vulcan():
    ws = FakeWS([
        {"headers": {"mid": "reg-1"}, "code": 200},
        {"headers": {"mid": "p-1", "sid": "s"}, "lwp": "/s/sync"},
        {"headers": {"mid": "p-2", "sid": "s"}, "lwp": "/s/vulcan"},
    ])
    assert asyncio.run(wait_ready(ws, timeout=5.0)) is True
    # 每个下行帧都回了 ack
    assert len(ws.sent) == 3
    assert all(a["code"] == 200 for a in ws.sent)


def test_wait_ready_times_out_without_vulcan():
    ws = FakeWS([{"headers": {"mid": "p-1"}, "lwp": "/s/sync"}])
    assert asyncio.run(wait_ready(ws, timeout=0.3)) is False


def test_recv_ack_matches_by_mid():
    ws = FakeWS([
        {"headers": {"mid": "other"}, "lwp": "/s/sync"},
        {"headers": {"mid": "mine"}, "code": 200, "body": {"messageId": "srv-1"}},
    ])
    ack = asyncio.run(recv_ack(ws, "mine", timeout=5.0))
    assert ack is not None
    assert ack["code"] == 200
    assert ack["body"]["messageId"] == "srv-1"
    # 不匹配的下行帧被 ack，匹配的那帧不回 ack
    assert [a["headers"]["mid"] for a in ws.sent] == ["other"]


def test_recv_ack_surfaces_rejection():
    """服务端拒绝时必须把 400 透出来，不能当成成功。"""
    ws = FakeWS([{"headers": {"mid": "mine"}, "code": 400}])
    ack = asyncio.run(recv_ack(ws, "mine", timeout=5.0))
    assert ack is not None
    assert ack["code"] == 400


def test_recv_ack_times_out():
    ws = FakeWS([])
    assert asyncio.run(recv_ack(ws, "mine", timeout=0.3)) is None


@pytest.mark.parametrize("junk", ["not json", "[1,2,3]"])
def test_recv_json_skips_non_dict_frames(junk):
    """非 JSON / 非 dict 帧不能让循环崩掉。"""

    class JunkWS(FakeWS):
        async def recv(self) -> str:
            if self._frames:
                return json.dumps(self._frames.pop(0))
            if not getattr(self, "_junked", False):
                self._junked = True
                return junk
            await asyncio.sleep(3600)

    ws = JunkWS([{"headers": {"mid": "p"}, "lwp": "/s/vulcan"}])
    assert asyncio.run(wait_ready(ws, timeout=5.0)) is True
