"""List every Daily room on the account. Used to prove the spike left nothing behind."""

from __future__ import annotations

import asyncio
import json

import aiohttp
from dotenv import load_dotenv

from ledgerline.config import Settings

load_dotenv(override=True)


async def main() -> None:
    settings = Settings()
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.daily.co/v1/rooms",
            headers={"Authorization": f"Bearer {settings.daily_api_key}"},
        ) as response:
            body = await response.json()
    print(f"HTTP {response.status} total_count={body.get('total_count')}")
    print(json.dumps([r["name"] for r in body.get("data", [])], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
