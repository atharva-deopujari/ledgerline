"""The store tests truncate tables, so they must never be pointed at a real database.

A live call lost its `users` row mid-call to a test run on the same database, and `record_call`
then failed on the foreign key. The fixture owns that guarantee, so the guarantee has a test.
"""

from __future__ import annotations

import pytest

from tests.store.conftest import as_test_database, guard


def test_the_test_database_is_derived_from_the_real_one():
    assert (
        as_test_database("postgresql://ledgerline:ledgerline@localhost:5432/ledgerline")
        == "postgresql://ledgerline:ledgerline@localhost:5432/ledgerline_test"
    )


def test_a_name_that_is_already_a_test_database_is_left_alone():
    dsn = "postgresql://u:p@host:5432/ledgerline_test"
    assert as_test_database(dsn) == dsn


def test_query_parameters_survive_the_swap():
    assert as_test_database("postgresql://u:p@host/app?sslmode=require") == (
        "postgresql://u:p@host/app_test?sslmode=require"
    )


def test_the_fixture_refuses_a_database_that_is_not_a_test_database():
    """The one that matters: whatever is in the environment, these tests do not truncate it."""
    with pytest.raises(RuntimeError, match="ledgerline"):
        guard("postgresql://ledgerline:ledgerline@localhost:5432/ledgerline")
    guard("postgresql://ledgerline:ledgerline@localhost:5432/ledgerline_test")
