"""The guard between Deepgram and the model: money reaches the model as rupees.

Deepgram's `smart_format` read "two fifty rupees" as `$2.50` in the owner's call, the coach
recorded 2.50, flagged it as implausibly small, and recorded 2.50 again when the correction
carried the same misreading. Formatting is off now, and this is the belt: the only currency here
is rupees, so a currency symbol in a transcript is a mistake we can see and undo.
"""

from __future__ import annotations

import pytest
from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection

from ledgerline.voice.spoken import SpokenText


class Recording(SpokenText):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        self.frames.append(frame)


async def said(text: str) -> str:
    guard = Recording()
    await guard.process_frame(
        TranscriptionFrame(user_id="u", timestamp="t", text=text), FrameDirection.DOWNSTREAM
    )
    return guard.frames[-1].text


@pytest.mark.parametrize(
    ("heard", "expected"),
    [
        ("My phone bill is $2.50 rupees.", "My phone bill is 2.50 rupees."),
        ("It is ₹250 a month", "It is 250 a month"),
        ("£11,000 for rent", "11,000 for rent"),
        ("Rent is 13,000 rupees", "Rent is 13,000 rupees"),
        ("", ""),
    ],
)
async def test_a_currency_symbol_is_stripped(heard, expected):
    """The only currency on this call is rupees; a symbol is Deepgram's, never the person's."""
    assert await said(heard) == expected


async def test_what_deepgram_sent_is_logged_beside_what_the_model_saw():
    """So a call's log shows the difference rather than only the corrected text.

    The recorder counts its warnings off the same loguru stream, which is why this is captured
    with a sink rather than caplog.
    """
    from loguru import logger

    lines: list[str] = []
    sink = logger.add(lines.append, level="INFO")
    try:
        guard = Recording()
        await guard.process_frame(
            TranscriptionFrame(user_id="u", timestamp="t", text="It is $2.50 rupees"),
            FrameDirection.DOWNSTREAM,
        )
    finally:
        logger.remove(sink)

    assert any("$2.50" in line and "2.50 rupees" in line for line in lines)


async def test_text_without_a_symbol_is_passed_through_untouched():
    """A frame nobody needs to change must arrive as the same object, not a copy."""
    guard = Recording()
    frame = TranscriptionFrame(user_id="u", timestamp="t", text="Rent is 13,000")

    await guard.process_frame(frame, FrameDirection.DOWNSTREAM)

    assert guard.frames[-1] is frame
