"""Spike item 5: what nova-3 does with language=en-IN, and how "forty-two hundred" transcribes.

Speech is synthesised with Deepgram Aura-2 (cheap, same $200 credit) so no Cartesia minutes and
no human are spent. Synthetic speech is cleaner than a real Indian-English speaker, so treat the
transcripts as a floor on quality, not a measurement of it.

    PYTHONPATH=. uv run python spike/probe_stt.py
    PYTHONPATH=. uv run python spike/probe_stt.py --numbers   # smart_format on vs off
"""

from __future__ import annotations

import asyncio
import json
import sys

import aiohttp
import websockets
from dotenv import load_dotenv

from ledgerline.config import Settings

load_dotenv(override=True)

SAMPLE_RATE = 16000
PHRASES = [
    "My EMI is, um, forty-two hundred.",
    "My salary is forty-five thousand rupees and rent is eleven thousand.",
    "Yes.",
    "The electricity bill is around one thousand two hundred, due on the fifteenth.",
]


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


async def transcribe(
    settings: Settings, pcm: bytes, language: str, smart_format: bool = True
) -> dict:
    url = (
        "wss://api.deepgram.com/v1/listen?model=nova-3-general"
        f"&language={language}&smart_format={str(smart_format).lower()}"
        "&numerals=true&interim_results=true"
        f"&encoding=linear16&sample_rate={SAMPLE_RATE}&channels=1"
        "&keyterm=EMI&keyterm=rupees&keyterm=lakh&keyterm=crore"
    )
    finals: list[str] = []
    metadata: dict = {}
    async with websockets.connect(
        url, additional_headers={"Authorization": f"Token {settings.deepgram_api_key}"}
    ) as ws:

        async def receive() -> None:
            async for raw in ws:
                event = json.loads(raw)
                if event.get("type") == "Results" and event.get("is_final"):
                    text = event["channel"]["alternatives"][0]["transcript"]
                    if text:
                        finals.append(text)
                elif event.get("type") == "Metadata":
                    metadata.update(event)

        reader = asyncio.create_task(receive())
        chunk = SAMPLE_RATE // 10 * 2  # 100 ms
        for offset in range(0, len(pcm), chunk):
            await ws.send(pcm[offset : offset + chunk])
            await asyncio.sleep(0.01)
        await ws.send(json.dumps({"type": "CloseStream"}))
        await asyncio.wait_for(reader, timeout=15)
    return {"transcript": " ".join(finals), "metadata": metadata}


NUMBER_PHRASES = [
    "two fifty rupees",
    "two hundred and fifty rupees",
    "twenty five hundred rupees",
    "twelve thousand five hundred",
    "thirteen thousand",
    "two point five",
    "on the twentieth of September",
    "fifteen percent",
]


async def numbers(settings: Settings) -> None:
    """`--numbers`: the same amounts with smart_format on and off, language=en-IN."""
    print("\n=== nova-3-general, language=en-IN, numerals=true ===")
    for phrase in NUMBER_PHRASES:
        pcm = await synthesise(settings, phrase)
        on = await transcribe(settings, pcm, "en-IN", smart_format=True)
        off = await transcribe(settings, pcm, "en-IN", smart_format=False)
        print(f"  said        : {phrase}")
        print(f"  smart_format on : {on['transcript']!r}")
        print(f"  smart_format off: {off['transcript']!r}")


async def main() -> None:
    settings = Settings()
    settings.validate_for_boot()

    if "--numbers" in sys.argv:
        await numbers(settings)
        return

    for language in ("en", "en-IN"):
        print(f"\n=== nova-3-general, language={language} ===")
        for phrase in PHRASES:
            pcm = await synthesise(settings, phrase)
            result = await transcribe(settings, pcm, language)
            print(f"  said : {phrase}")
            print(f"  heard: {result['transcript']!r}")
        models = result["metadata"].get("model_info") or result["metadata"].get("models")
        print(f"  model_info reported by Deepgram: {json.dumps(models)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
