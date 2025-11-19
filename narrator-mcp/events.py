"""Utilities for sending events back to the Bridge."""

from __future__ import annotations

import base64
import binascii
import inspect
import json
from typing import Any, Awaitable, Callable, Dict, Protocol, Union


class SenderProtocol(Protocol):
    async def send(self, message: str) -> Any:  # pragma: no cover - protocol marker
        ...


SendCallable = Callable[[Dict[str, Any]], Awaitable[None]]
SendTarget = Union[SenderProtocol, SendCallable]


async def _dispatch(target: SendTarget, payload: Dict[str, Any]) -> None:
    """Attempts to deliver a payload to the provided send target."""
    if hasattr(target, "send"):
        await target.send(json.dumps(payload))
        return

    result = target(payload)  # type: ignore[operator]
    if inspect.isawaitable(result):
        await result


def _encode_audio(audio_bytes: bytes, encoding: str) -> str:
    if encoding == "base64":
        return base64.b64encode(audio_bytes).decode("utf-8")
    if encoding == "hex":
        return binascii.hexlify(audio_bytes).decode("utf-8")
    raise ValueError(f"Unsupported audio encoding: {encoding}")


async def send_text_event(send: SendTarget, token: str) -> None:
    """Sends a single text token event."""
    await _dispatch(send, {"event": "text_token", "data": token})


async def send_audio_event(
    send: SendTarget,
    audio_bytes: bytes,
    *,
    encoding: str = "base64",
) -> None:
    """Sends an encoded audio chunk event."""
    payload = _encode_audio(audio_bytes, encoding)
    await _dispatch(
        send,
        {
            "event": "audio_chunk",
            "data": payload,
            "encoding": encoding,
        },
    )


__all__ = ["send_audio_event", "send_text_event"]
