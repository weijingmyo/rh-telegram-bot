"""Pytest fixtures."""

from __future__ import annotations

import pytest
import pytest_asyncio

from src.storage import Database


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    yield database
    await database.close()
