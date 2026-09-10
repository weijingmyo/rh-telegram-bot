"""Blacklist threshold unit tests."""

from __future__ import annotations

import pytest

from src.blacklist import BlacklistService


@pytest.mark.asyncio
async def test_blacklist_after_three_alerts(db):
    svc = BlacklistService(db, limit=3)

    d1 = await svc.record_alert("dev", "0xABC")
    assert d1.entity.alert_count == 1
    assert not d1.entity.blacklisted
    assert d1.progress == "1/3"
    assert d1.allowed

    d2 = await svc.record_alert("dev", "0xABC")
    assert d2.entity.alert_count == 2
    assert not d2.entity.blacklisted

    d3 = await svc.record_alert("dev", "0xAbc")  # case-insensitive for dev
    assert d3.entity.alert_count == 3
    assert d3.entity.blacklisted

    check = await svc.check("dev", "0xabc")
    assert not check.allowed
    assert check.entity.blacklisted


@pytest.mark.asyncio
async def test_twitter_and_dev_tracked_separately(db):
    svc = BlacklistService(db, limit=3)
    await svc.record_alert("twitter", "ElonMusk")
    await svc.record_alert("twitter", "elonmusk")
    tw = await svc.check("twitter", "@ElonMusk")
    assert tw.entity.alert_count == 2
    assert not tw.entity.blacklisted

    dev = await svc.check("dev", "0x1")
    assert dev.entity.alert_count == 0


@pytest.mark.asyncio
async def test_no_increment_when_already_blacklisted(db):
    svc = BlacklistService(db, limit=3)
    for _ in range(3):
        await svc.record_alert("twitter", "kol")
    before = await svc.check("twitter", "kol")
    assert before.entity.blacklisted
    after = await svc.record_alert("twitter", "kol")
    assert after.entity.alert_count == before.entity.alert_count
