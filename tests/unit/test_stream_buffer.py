"""Stream buffer tests."""

from __future__ import annotations

import pytest

from backend.core.stream_buffer import StreamBuffer


@pytest.mark.asyncio
async def test_stream_buffer_append_and_snapshot():
    buf = StreamBuffer()
    await buf.append("t1", assignment_id="a1", agent="Coder", chunk="hello ")
    await buf.append("t1", assignment_id="a1", agent="Coder", chunk="world")
    snap = await buf.snapshot("t1")
    assert snap["partial_result"] == "hello world"
    assert snap["streaming_agent"] == "Coder"
    await buf.finish("t1")
    assert await buf.snapshot("t1") == {}
