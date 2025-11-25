"""Tests for the token chunking helper."""

from __future__ import annotations

from chunker import Chunker


def test_sentence_boundary_chunking_creates_block() -> None:
    chunker = Chunker(max_tokens=50, sentence_boundary=True)
    tokens = ["Hello", " world", "!"]

    block = None
    for token in tokens:
        block = chunker.add_token(token)

    assert block == "Hello world!"
    # Buffer should be empty after emitting a block
    assert chunker.flush() is None


def test_max_tokens_chunk_without_sentence_detection() -> None:
    chunker = Chunker(max_tokens=3, sentence_boundary=False)
    tokens = ["This", " is", " fine", " still"]

    first = None
    for token in tokens:
        chunk = chunker.add_token(token)
        if chunk:
            first = chunk
            break

    assert first == "This is fine"


def test_flush_returns_leftover_content_once() -> None:
    chunker = Chunker(max_tokens=10, sentence_boundary=True)
    chunker.add_token("Left")
    chunker.add_token(" over")

    leftover = chunker.flush()
    assert leftover == "Left over"
    assert chunker.flush() is None
