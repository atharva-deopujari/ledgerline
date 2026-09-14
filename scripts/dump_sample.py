"""Write frontend/src/protocol/sample.json from the real domain layer.

`sample.json` is the shape the frontend parses against, and it had no generator: tests only read
it, so it drifted from `build_cards` for days without anything failing. It is now built the same
way `dump_mock_snapshots.py` builds the mock journey -- from a state the engine can actually
produce -- and `tests/domain/test_cards.py` fails if the committed file is not what this script
writes.

    uv run python scripts/dump_sample.py

Re-run it whenever the cards contract changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ledgerline.domain.cards import MAX_BYTES, CardsMessage, build_cards  # noqa: E402
from ledgerline.domain.engine import build_plan  # noqa: E402
from tests.domain.test_cards import sample_state  # noqa: E402

OUT = ROOT / "frontend" / "src" / "protocol" / "sample.json"
VERSION = 7
FOCUS = "essentials"


def sample_json() -> str:
    """The file's exact contents, so the test can compare rather than reimplement."""
    state = sample_state()
    message = build_cards(state, build_plan(state), version=VERSION, focus=FOCUS)
    payload = message.model_dump_json()
    assert CardsMessage.model_validate_json(payload) == message
    assert len(payload.encode()) <= MAX_BYTES, len(payload)
    return json.dumps(json.loads(payload), indent=2) + "\n"


def main() -> None:
    text = sample_json()
    OUT.write_text(text)
    print(f"wrote {OUT} {len(text.encode())} bytes")


if __name__ == "__main__":
    main()
