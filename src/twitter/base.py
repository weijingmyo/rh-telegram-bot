"""Twitter/X provider interface — swap implementations without touching scanner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class TweetMatch:
    tweet_id: str
    text: str
    url: str
    author_id: str
    author_username: str
    author_name: str
    followers_count: int
    verified: bool = False
    raw: dict = field(default_factory=dict)


class TwitterProvider(ABC):
    """Abstract search provider."""

    @abstractmethod
    async def search_address(self, address: str, *, max_results: int = 20) -> list[TweetMatch]:
        """Search recent posts containing the exact wallet address."""

    @abstractmethod
    async def close(self) -> None:
        ...

    @property
    @abstractmethod
    def configured(self) -> bool:
        ...


class NullTwitterProvider(TwitterProvider):
    """No-op provider used when credentials are missing."""

    @property
    def configured(self) -> bool:
        return False

    async def search_address(self, address: str, *, max_results: int = 20) -> list[TweetMatch]:
        return []

    async def close(self) -> None:
        return None
