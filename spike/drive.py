"""A fake user for the spike: joins the room, speaks synthesised audio, logs every app-message.

Usage: `PYTHONPATH=. uv run python spike/drive.py <room_url> <meeting_token>` — the token is
required because rooms are private; `spike/spike_bot.py` prints a guest one beside the URL.

Answers spike items 1 (turn-end delay) and 2 (does the generic urgent frame reach a remote
participant through DailyTransport) without a human at a microphone. The speech is Deepgram
Aura-2, so the prosody is cleaner than a real speaker's; Smart Turn is a prosody model, so
treat the turn-end numbers as indicative and confirm the "yes" case with a human before
trusting it.

    PYTHONPATH=. uv run python spike/drive.py <room_url> [meeting_token]

Rooms are private, so the token from POST /api/sessions is required to join.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time

import aiohttp
from daily import CallClient, Daily, EventHandler
from dotenv import load_dotenv

from ledgerline.config import Settings

load_dotenv(override=True)

SAMPLE_RATE = 16000
ALL_UTTERANCES: list[str | list[str]] = [
    "I have eight thousand rupees in my account right now.",
    "My salary is forty-five thousand rupees on the first.",
    "My rent is eleven thousand rupees, due on the fifth.",
    "I spend about two thousand rupees on groceries every month.",
]

# SPIKE_SCRIPT=hesitant replays the shape of the owner's third live call: one intended
# utterance spoken in fragments with a real pause after a function word, which is what split
# "I have" / "20,000 in cash and" / "20,000 in bank balance." into three user turns.
HESITANT_UTTERANCES: list[list[str] | str] = [
    ["I have", "twenty thousand in cash and", "twenty thousand in bank balance."],
    ["It is", "on", "September eighteenth."],
    # Single-word answers are most of a real call's turns, and the completion judge has to
    # decide them too. Their first-audio is the number that says whether it costs a round trip.
    "Yes.",
    "Nothing.",
    ["My rent is", "eleven thousand rupees."],
]

# How long the person stops mid-sentence. Long enough that VAD certainly sees silence.
HESITATION_SECS = float(os.getenv("SPIKE_HESITATION_SECS", "1.6"))
# SPIKE_UTTERANCES=1 keeps a Cartesia pass to a single short exchange.
_SCRIPT = HESITANT_UTTERANCES if os.getenv("SPIKE_SCRIPT") == "hesitant" else ALL_UTTERANCES
UTTERANCES = _SCRIPT[: int(os.getenv("SPIKE_UTTERANCES", len(_SCRIPT)))]
GAP_SECS = float(os.getenv("SPIKE_GAP_SECS", "12"))  # time for the bot to answer


def silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


async def synthesise_utterance(settings: Settings, utterance: str | list[str]) -> bytes:
    """One utterance as a single stream of audio, with real silence between its fragments."""
    if isinstance(utterance, str):
        return await synthesise(settings, utterance)
    clips = [await synthesise(settings, fragment) for fragment in utterance]
    gap = silence(HESITATION_SECS)
    return gap.join(clips)


async def synthesise(settings: Settings, text: str) -> bytes:
    url = (
        "https://api.deepgram.com/v1/speak?model=aura-2-thalia-en"
        f"&encoding=linear16&sample_rate={SAMPLE_RATE}&container=none"
    )
    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            headers={"Authorization": f"Token {settings.deepgram_api_key}"},
            json={"text": text},
        ) as response:
            response.raise_for_status()
            return await response.read()


class FakeUser(EventHandler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict] = []
        self.joined = threading.Event()
        self.client = CallClient(event_handler=self)

    def on_app_message(self, message, sender) -> None:
        label = message.get("label") if isinstance(message, dict) else None
        kind = "rtvi" if label == "rtvi-ai" else "APP"
        print(f"[{time.strftime('%H:%M:%S')}] {kind} app-message: {json.dumps(message)[:220]}")
        self.messages.append(message if isinstance(message, dict) else {"raw": str(message)})

    def on_participant_joined(self, participant) -> None:
        print(f"participant joined: {participant['info'].get('userName')}")

    def on_error(self, message) -> None:
        print(f"ERROR: {message}")


async def main() -> None:
    room_url = sys.argv[1]
    token = sys.argv[2] if len(sys.argv) > 2 else None
    settings = Settings()
    clips = [
        (u if isinstance(u, str) else " … ".join(u), await synthesise_utterance(settings, u))
        for u in UTTERANCES
    ]

    Daily.init()
    mic = Daily.create_microphone_device("fake-user-mic", sample_rate=SAMPLE_RATE, channels=1)
    user = FakeUser()
    user.client.update_inputs(
        {
            "camera": False,
            "microphone": {"isEnabled": True, "settings": {"deviceId": "fake-user-mic"}},
        }
    )
    user.client.join(room_url, token, completion=lambda data, error: user.joined.set())
    user.joined.wait(timeout=20)
    print("fake user joined; waiting for the bot's greeting")
    await asyncio.sleep(8)

    for text, pcm in clips:
        print(f"\n[{time.strftime('%H:%M:%S')}] SPEAKING: {text}")
        await asyncio.to_thread(mic.write_frames, pcm)
        print(f"[{time.strftime('%H:%M:%S')}] finished speaking, waiting {GAP_SECS}s")
        await asyncio.sleep(GAP_SECS)

    app_messages = [m for m in user.messages if m.get("label") != "rtvi-ai"]
    print(f"\nnon-RTVI app-messages received: {len(app_messages)}")
    for message in app_messages:
        print("  ", json.dumps(message)[:220])

    user.client.leave()
    await asyncio.sleep(2)
    user.client.release()
    Daily.deinit()


if __name__ == "__main__":
    asyncio.run(main())
