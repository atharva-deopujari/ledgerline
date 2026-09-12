"""Headless half of the spike: the checks that need no microphone and no browser.

Answers spike items 3 (partly), 4, 5a and 6. Items 1, 2 and 5b need a real call.

    uv run python spike/probe.py
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import aiohttp
from dotenv import load_dotenv

from ledgerline.config import Settings

load_dotenv(override=True)


async def record_number(params, value: float) -> None:
    """Record a number the person said out loud.

    Args:
        value: The number, as a plain number.
    """


def probe_4_tool_schema() -> list[dict]:
    """Item 4: does the schema Pipecat derives from a direct function carry strict: true?"""
    from pipecat.adapters.services.open_ai_responses_adapter import OpenAIResponsesLLMAdapter
    from pipecat.processors.aggregators.llm_context import LLMContext

    context = LLMContext(tools=[record_number])
    params = OpenAIResponsesLLMAdapter().get_llm_invocation_params(context)
    tools = params.get("tools")
    print("=== 4. derived tool schema, exactly as the Responses service sends it ===")
    print(json.dumps(tools, indent=2, default=str))
    return tools


async def probe_5a_deepgram_language(settings: Settings) -> None:
    """Item 5a: does nova-3 accept language=en-IN, or does the socket get rejected?"""
    import websockets

    for language in ("en", "en-IN"):
        url = (
            "wss://api.deepgram.com/v1/listen?model=nova-3-general"
            f"&language={language}&smart_format=true&numerals=true&encoding=linear16"
            "&sample_rate=16000&channels=1"
        )
        print(f"=== 5a. Deepgram nova-3 language={language} ===")
        try:
            async with websockets.connect(
                url, additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"}
            ) as ws:
                await ws.send(b"\x00\x00" * 1600)  # 100 ms of silence
                await ws.send(json.dumps({"type": "CloseStream"}))
                reply = await asyncio.wait_for(ws.recv(), timeout=10)
                print(f"ACCEPTED. first message: {str(reply)[:200]}")
        except Exception as exc:
            print(f"REJECTED. {type(exc).__name__}: {exc}")


async def probe_3_llm(settings: Settings, tools: list[dict]) -> None:
    """Item 3: gpt-5.6-luna over /v1/responses with the derived tool, and time to first token."""
    body = {
        "model": settings.openai_model,
        "input": [
            {"role": "system", "content": "Call record_number when the person says a number."},
            {"role": "user", "content": "my EMI is forty-two hundred"},
        ],
        "tools": tools,
        "reasoning": {"effort": "none"},
        "stream": True,
        "store": False,
        "max_output_tokens": 120,
    }
    print("=== 3. gpt-5.6-luna via /v1/responses, streaming, with the derived tool ===")
    start = time.monotonic()
    first = None
    events: list[str] = []
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=body,
        ) as response:
            if response.status != 200:
                print(f"HTTP {response.status}: {(await response.text())[:400]}")
                return
            async for raw in response.content:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                if first is None:
                    first = time.monotonic() - start
                event = json.loads(line[5:].strip())
                events.append(event.get("type", "?"))
                if event.get("type") == "response.output_item.done":
                    print("  output item:", json.dumps(event["item"])[:300])
    print(f"  time to first streamed event: {first:.3f}s")
    print(f"  total: {time.monotonic() - start:.3f}s, {len(events)} events")


async def probe_6_room_delete(settings: Settings) -> None:
    """Item 6: can a room be DELETEd immediately after it is created?"""
    from ledgerline.voice.transport import create_room, delete_room, room_name_from_url

    print("=== 6. Daily room DELETE right after create ===")
    room_url, room_name = await create_room(settings)
    print(f"  created {room_url}")
    async with aiohttp.ClientSession() as session:
        async with session.delete(
            f"https://api.daily.co/v1/rooms/{room_name}",
            headers={"Authorization": f"Bearer {settings.daily_api_key}"},
        ) as response:
            print(f"  DELETE -> HTTP {response.status} {(await response.text())[:200]}")
    print(f"  helper delete_room (already gone) -> {await delete_room(settings, room_name)}")
    assert room_name_from_url(room_url) == room_name


async def main() -> None:
    settings = Settings()
    settings.validate_for_boot()
    tools = probe_4_tool_schema()
    await probe_5a_deepgram_language(settings)
    await probe_3_llm(settings, tools)
    await probe_6_room_delete(settings)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    asyncio.run(main())
