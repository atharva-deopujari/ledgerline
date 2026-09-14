"""One short word while a tool runs, so the person is not left listening to silence.

Session B's prompt change makes the model call tools silently and speak once after the result.
That fixes the doubled questions from the owner's third call ("What else would you like to tell
me?What's your next income or expense?") but it removes the speech that used to cover the tool
round trip. This puts a single acknowledgement back, from the pipeline rather than the model,
so it can never turn into a second question.

`done` is excluded: the model says one goodbye and calls it in the same reply, and a filler on
top of that would be a second farewell.
"""

from __future__ import annotations

from itertools import cycle

from pipecat.frames.frames import (
    Frame,
    FunctionCallInProgressFrame,
    TTSSpeakFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

FILLERS = ("Okay.", "Got it.", "Noted.")

# The model owns the goodbye, and `done` is the tool it says it with.
NEVER_FILLED = frozenset({"done"})


class ActionFiller(FrameProcessor):
    """Speaks once per user turn, the moment the first tool call starts."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._fillers = cycle(FILLERS)
        self._spoken_this_turn = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)

        if isinstance(frame, UserStartedSpeakingFrame | UserStoppedSpeakingFrame):
            self._spoken_this_turn = False
        elif isinstance(frame, FunctionCallInProgressFrame):
            if not self._spoken_this_turn and frame.function_name not in NEVER_FILLED:
                self._spoken_this_turn = True
                await self.push_frame(TTSSpeakFrame(text=next(self._fillers)), direction)

        await self.push_frame(frame, direction)
