"""Follower filter unit tests."""

from __future__ import annotations

from src.blacklist import should_alert_followers
from src.twitter.base import TweetMatch


def test_follower_threshold_strictly_greater():
    assert should_alert_followers(10001, 10000)
    assert not should_alert_followers(10000, 10000)
    assert not should_alert_followers(9999, 10000)


def test_filter_tweet_matches():
    tweets = [
        TweetMatch(
            tweet_id="1",
            text="0xabc",
            url="https://x.com/a/status/1",
            author_id="1",
            author_username="small",
            author_name="s",
            followers_count=500,
        ),
        TweetMatch(
            tweet_id="2",
            text="0xabc",
            url="https://x.com/b/status/2",
            author_id="2",
            author_username="big",
            author_name="b",
            followers_count=25000,
        ),
    ]
    big = [t for t in tweets if should_alert_followers(t.followers_count, 10000)]
    assert len(big) == 1
    assert big[0].author_username == "big"
