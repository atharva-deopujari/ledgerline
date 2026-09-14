"""What Deepgram sent, and what the model is allowed to see.

The owner's call of 14 September: the person said "two fifty rupees" for a phone bill and
`smart_format` delivered `$2.50 per month`. The coach recorded 2.50, said it sounded too small —
which was right — and then recorded 2.50 again, because the correction came back through the same
formatter as `Not 2.5. It's $2.50 rupees.` It took three attempts to land 250.

Formatting is off at the source now (see `pipeline.STT_SMART_FORMAT` and the table in
spike-findings.md). This is the belt beside it: the only currency on this call is rupees, so a
currency symbol in a transcript is Deepgram's, never the person's, and it is removed before the
model reads it. What arrived is logged beside what was passed on, so a recording shows the
difference rather than only the corrected text.
"""

from __future__ import annotations

import re

from loguru import logger
from pipecat.frames.frames import Frame, TranscriptionFrame
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# A symbol immediately before a figure. Not a bare "$" in prose: this fires on money.
CURRENCY = re.compile(r"[$£€₹¥](?=\s?\d)")


class SpokenText(FrameProcessor):
    """Cleans a transcript of anything only a formatter could have put there."""

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame) and CURRENCY.search(frame.text):
            cleaned = CURRENCY.sub("", frame.text)
            # INFO, not DEBUG: a live call runs at INFO and this is the line that explains a
            # figure the person never said.
            logger.info("stt currency stripped: {!r} -> {!r}", frame.text, cleaned)
            frame.text = cleaned

        await self.push_frame(frame, direction)
