"""The pipeline says one short word the moment a tool starts, so the person is not left waiting.

Session B's prompt change makes the model call tools silently and speak once after the result;
without this the gap between the person finishing and hearing anything is the whole tool round
trip. The model owns the goodbye, so `end_call` never gets a filler.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    FunctionCallInProgressFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    UserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from ledgerline.voice.filler import FILLERS, ActionFiller


class Recording(ActionFiller):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.frames = []

    async def push_frame(self, frame, direction=FrameDirection.DOWNSTREAM):
        self.frames.append(frame)


def spoken(filler):
    return [f.text for f in filler.frames if isinstance(f, TTSSpeakFrame)]


def in_progress(name="upsert_item", tool_call_id="c1"):
    return FunctionCallInProgressFrame(function_name=name, tool_call_id=tool_call_id, arguments={})


async def push(filler, *frames):
    for frame in frames:
        await filler.process_frame(frame, FrameDirection.DOWNSTREAM)


async def test_a_tool_call_gets_an_acknowledgement():
    filler = Recording()
    await push(filler, in_progress())
    assert spoken(filler) and spoken(filler)[0] in FILLERS


async def test_only_once_per_user_turn():
    """Four parallel upserts in one turn must not produce four "Okay."s."""
    filler = Recording()
    await push(filler, in_progress(tool_call_id="a"), in_progress(tool_call_id="b"))
    assert len(spoken(filler)) == 1


async def test_the_next_turn_gets_its_own():
    filler = Recording()
    await push(filler, in_progress(tool_call_id="a"))
    await push(filler, UserStoppedSpeakingFrame(), in_progress(tool_call_id="b"))
    assert len(spoken(filler)) == 2


async def test_end_call_alongside_another_tool_still_gets_the_other_one():
    filler = Recording()
    await push(filler, in_progress(name="upsert_item", tool_call_id="a"))
    assert len(spoken(filler)) == 1


async def test_the_call_still_travels_downstream():
    filler = Recording()
    frame = in_progress()
    await push(filler, frame)
    assert frame in filler.frames


async def test_fillers_rotate_so_the_bot_does_not_say_okay_every_time():
    filler = Recording()
    for i in range(len(FILLERS)):
        await push(filler, UserStoppedSpeakingFrame(), in_progress(tool_call_id=str(i)))
    assert sorted(spoken(filler)) == sorted(FILLERS)


async def test_a_transcript_alone_says_nothing():
    filler = Recording()
    await push(filler, TranscriptionFrame(user_id="u", timestamp="t", text="rent is 11,000"))
    assert spoken(filler) == []


async def test_the_v2_goodbye_tool_gets_no_filler():
    """`done` folds in `end_call`, so it owns the goodbye the way `end_call` did."""
    filler = Recording()

    await push(filler, UserStoppedSpeakingFrame(), in_progress(name="done"))

    assert spoken(filler) == []
