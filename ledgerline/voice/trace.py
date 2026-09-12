"""Frame-level trace of one call, for answering "what ended that turn?".

Only attached when `log_level` is DEBUG. The turn machinery in Pipecat 1.9 spans the transport,
the VAD, the turn analyzer, our gate and the aggregator, and the only way to see which of them
ended a turn is to watch the frames go past with timestamps.
"""

from __future__ import annotations

import datetime as dt

from loguru import logger
from pipecat.frames.frames import (
    InterimTranscriptionFrame,
    LLMRunFrame,
    TranscriptionFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    UserTurnInferenceCompletedFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.observers.base_observer import BaseObserver, FramePushed

WATCHED = (
    InterimTranscriptionFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    UserTurnInferenceCompletedFrame,
    LLMRunFrame,
)


class FrameTrace(BaseObserver):
    """Logs every turn-relevant frame with its source processor and a wall clock."""

    def __init__(self) -> None:
        super().__init__()
        self._seen: set[int] = set()

    async def on_push_frame(self, data: FramePushed) -> None:
        frame = data.frame
        if not isinstance(frame, WATCHED) or frame.id in self._seen:
            return
        self._seen.add(frame.id)
        text = getattr(frame, "text", "")
        logger.debug(
            "TRACE {} {} from={} {}",
            dt.datetime.now().strftime("%H:%M:%S.%f")[:-3],
            type(frame).__name__,
            getattr(data.source, "name", "?"),
            repr(text[:60]) if text else "",
        )
