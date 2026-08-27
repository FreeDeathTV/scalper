"""Live capture tests: utterance splitting + /capture/upload + /ws/live."""

from __future__ import annotations

import core.transcriber as transcriber_mod
import numpy as np
import pytest
from core.live import UtteranceBuffer
from core.transcriber import AsrChunkResult
from fastapi.testclient import TestClient
from ipc.schemas import Settings

SR = 16_000


def _speech(seconds: float, amp: float = 0.3) -> np.ndarray:
    t = np.linspace(0, seconds, int(SR * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * 300 * t)).astype(np.float32)


def _zeros(seconds: float) -> np.ndarray:
    return np.zeros(int(SR * seconds), dtype=np.float32)


# ------------------------------------------------------------- splitter


def test_utterance_closes_after_hangover_silence():
    buf = UtteranceBuffer()
    assert buf.feed(_speech(1.5)) == []  # still open while speech runs
    for _ in range(5):  # 5 x 100ms — below hangover 0.6
        assert buf.feed(_zeros(0.1)) == []
    out = buf.feed(_zeros(0.1))  # cumulative silence hits 0.6 → close
    assert len(out) == 1
    start, end, pcm = out[0]
    assert start == 0.0
    assert abs(end - 2.1) < 0.02  # speech + trailing silence is included
    assert pcm.shape[0] == int(2.1 * SR)


def test_sub_min_blip_is_dropped_as_noise():
    buf = UtteranceBuffer(min_utterance_s=0.35)
    out = buf.feed(_speech(0.1))
    out += buf.feed(_zeros(1.0))
    assert out == []


def test_force_flush_at_max_length_without_trailing_silence():
    buf = UtteranceBuffer(max_utterance_s=2.0)
    out: list[tuple[float, float, np.ndarray]] = []
    for _ in range(12):  # 3s of continuous speech
        out += buf.feed(_speech(0.25))
    assert len(out) == 1
    _, end, _ = out[0]
    assert abs(end - 2.0) < 0.01


def test_flush_emits_tail_only_with_speech():
    buf = UtteranceBuffer()
    assert buf.flush() is None
    buf.feed(_speech(0.8))
    tail = buf.flush()
    assert tail is not None
    start, end, _ = tail
    assert (start, end) == (0.0, 0.8)
    assert buf.flush() is None  # drained


def test_absolute_timestamps_across_multiple_utterances():
    buf = UtteranceBuffer(hangover_s=0.4)
    stamps: list[tuple[float, float]] = []
    for _ in range(2):
        buf.feed(_speech(1.0))
        stamps += [(s, e) for s, e, _ in buf.feed(_zeros(0.5))]
    assert [round(s, 2) for s, _ in stamps] == [0.0, 1.5]
    assert [round(e, 2) for _, e in stamps] == [1.5, 3.0]


# ------------------------------------------------------------ endpoints


class _FakeEngine:
    name = "fake"

    def available(self) -> bool:
        return True

    def load(self, settings: Settings) -> None: ...

    def unload(self) -> None: ...

    def transcribe_chunk(
        self, pcm: np.ndarray, start_s: float, end_s: float, settings: Settings, **kw: object
    ) -> AsrChunkResult:
        return AsrChunkResult(text="hello world", language="en", start_s=start_s, end_s=end_s)


@pytest.fixture()
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcriber_mod, "get_engine", lambda settings: _FakeEngine())


@pytest.fixture()
def client() -> TestClient:
    from main import app

    return TestClient(app)


def _drain_bus(sub: object) -> list[object]:
    """Collect everything queued on an already-subscribed broadcast queue."""
    import asyncio

    found: list[object] = []
    while True:
        try:
            found.append(sub.get_nowait())  # type: ignore[attr-defined]
        except (asyncio.QueueEmpty, RuntimeError):
            return found


def test_ws_live_emits_live_segment(fake_engine: None, client: TestClient) -> None:
    from main import bus

    sub = bus.subscribe("*")  # subscriber exists BEFORE publishing, like the real UI
    try:
        with client.websocket_connect("/ws/live") as ws:
            ws.send_json({"settings": {"model_size": "tiny"}})
            ack = ws.receive_json()
            assert set(ack) == {"session_id"}
            ws.send_bytes(_speech(1.0).tobytes())
            ws.send_bytes(_zeros(0.7).tobytes())  # crosses hangover → closes utterance
            ws.send_json({"action": "stop"})
            done = ws.receive_json()
            assert done["done"] is True and done["session_id"] == ack["session_id"]

        events = [
            dict(session_id=e.session_id, start_s=e.start_s, end_s=e.end_s, text=e.text)
            for e in _drain_bus(sub)
            if hasattr(e, "session_id") and hasattr(e, "text")
        ]
    finally:
        bus.unsubscribe("*", sub)
    assert len(events) == 1
    seg = events[0]
    assert seg["session_id"] == ack["session_id"]
    assert seg["text"] == "hello world"
    assert seg["start_s"] == 0.0
    assert abs(seg["end_s"] - 1.7) < 0.02


def test_upload_capture_returns_job(client: TestClient) -> None:
    junk = b"x" * 200  # intentionally not valid audio: job errors fast, no model load
    res = client.post(
        "/capture/upload",
        files={"file": ("cap.wav", junk, "audio/wav")},
        data={"settings_json": '{"model_size":"tiny"}'},
    )
    assert res.status_code == 200
    assert res.json()["job_id"].startswith("batch-")


def test_upload_rejects_empty_payload(client: TestClient) -> None:
    res = client.post(
        "/capture/upload",
        files={"file": ("cap.wav", b"", "audio/wav")},
    )
    assert res.status_code == 400


def test_cors_allows_webview_origin(client: TestClient) -> None:
    """The Tauri webview is a different origin than the loopback sidecar; cross-origin
    fetches/SSE must be allowed for it (dev localhost:1420 + packaged tauri.localhost)."""
    res = client.get(
        "/health",
        headers={"Origin": "http://localhost:1420"},
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "http://localhost:1420"
    res2 = client.get(
        "/health",
        headers={"Origin": "http://tauri.localhost"},
    )
    assert res2.headers.get("access-control-allow-origin") == "http://tauri.localhost"


def test_live_segment_serializes_as_live_segment_over_events() -> None:
    """The frontend only renders SSE frames whose `event` is 'live_segment'.
    Assert the SSE serialization contract (json.dumps(model_dump())) emits that
    discriminator with intact text/session_id/start_s — mirrors main.py /events.

    Single asyncio loop (asyncio.Queue is not thread-safe across loops), so we
    publish+drain on the same loop rather than over a concurrent TestClient SSE.
    """
    import asyncio
    import json

    from ipc.events import bus
    from ipc.schemas import LiveTranscriptEvent

    async def run() -> dict:
        q = bus.subscribe("*")
        try:
            bus.publish(
                LiveTranscriptEvent(
                    session_id="live-abc", start_s=0.0, end_s=1.7, text="hello world"
                )
            )
            ev = await asyncio.wait_for(q.get(), timeout=2.0)
            frame = f"data: {json.dumps(ev.model_dump())}\n\n"  # mirrors main.py
            payload = json.loads(frame[len("data:") :].strip())
            assert payload["event"] == "live_segment"
            assert payload["session_id"] == "live-abc"
            assert payload["start_s"] == 0.0
            assert payload["text"] == "hello world"
            return payload
        finally:
            bus.unsubscribe("*", q)

    loop = asyncio.new_event_loop()
    try:
        payload = loop.run_until_complete(run())
    finally:
        loop.close()
    assert payload["event"] == "live_segment"
