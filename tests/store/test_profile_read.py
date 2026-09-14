"""The read path has a deadline, because it sits between the person and the greeting."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.db

PHONE = "9876543210"


async def test_a_profile_that_does_not_answer_in_time_is_no_answer_at_all(store):
    """None is not []. None means the memory could not be read this time, and the call goes on
    without it; [] means there is nothing remembered, which is a first-time caller."""
    assert await store.load_active(PHONE, timeout=0.000001) is None
    assert await store.load_notes(PHONE, timeout=0.000001) is None


async def test_a_caller_with_nothing_remembered_gets_an_empty_list(store):
    assert await store.load_active(PHONE) == []
    assert await store.load_notes(PHONE) == []
