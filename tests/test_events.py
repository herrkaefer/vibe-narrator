"""Tests for event dispatch helpers."""

from __future__ import annotations

import asyncio

import pytest

from events import send_audio_event, send_text_event


def test_send_text_event_dispatches_payload() -> None:
    captured = []

    async def fake_send(payload):
        captured.append(payload)

    asyncio.run(send_text_event(fake_send, "token-1"))

    assert captured == [{"event": "text_token", "data": "token-1"}]


def test_send_audio_event_hex_encoding() -> None:
    captured = []

    async def fake_send(payload):
        captured.append(payload)

    audio = b"\x00\x01\xfe"
    asyncio.run(send_audio_event(fake_send, audio, encoding="hex"))

    assert captured == [
        {
            "event": "audio_chunk",
            "data": audio.hex(),
            "encoding": "hex",
        }
    ]


def test_send_audio_event_invalid_encoding_raises() -> None:
    async def fake_send(payload):  # pragma: no cover - should not be called
        raise AssertionError("dispatcher should not be invoked on error")

    with pytest.raises(ValueError):
        asyncio.run(send_audio_event(fake_send, b"noise", encoding="unknown"))
