"""ATH threshold unit tests."""

from __future__ import annotations

from src.blacklist import has_high_ath
from src.gmgn.models import CreatedToken, DevLaunchHistory, TokenInfo, AthTokenInfo


def test_has_high_ath_threshold():
    assert has_high_ath(800_000, 800_000)
    assert has_high_ath(800_001, 800_000)
    assert not has_high_ath(799_999, 800_000)
    assert not has_high_ath(0, 800_000)


def test_tokens_above_ath_filters():
    hist = DevLaunchHistory(
        wallet="0xdev",
        tokens=[
            CreatedToken(token_address="a", symbol="A", token_ath_mc=100_000),
            CreatedToken(token_address="b", symbol="B", token_ath_mc=800_000),
            CreatedToken(token_address="c", symbol="C", token_ath_mc=2_000_000),
        ],
        ath_mc=2_000_000,
    )
    prior = hist.tokens_above_ath(800_000)
    assert [t.symbol for t in prior] == ["B", "C"]


def test_ath_token_info_parse():
    info = TokenInfo.from_token_info(
        {
            "address": "0xtoken",
            "symbol": "NEW",
            "name": "New",
            "circulating_supply": "1000",
            "price": {"price": "1.5"},
            "liquidity": "5000",
            "dev": {
                "creator_address": "0xdev",
                "ath_token_info": {
                    "ath_token": "0xold",
                    "ath_mc": "1500000",
                    "symbol": "OLD",
                    "name": "Old Hit",
                },
            },
        },
        chain="robinhood",
    )
    assert info.creator_address == "0xdev"
    assert info.market_cap == 1500.0
    assert info.ath_token_info is not None
    assert info.ath_token_info.ath_mc == 1_500_000
    assert has_high_ath(info.ath_token_info.ath_mc, 800_000)


def test_exclude_self_from_prior():
    hist = DevLaunchHistory(
        wallet="0xdev",
        tokens=[
            CreatedToken(token_address="0xNEW", symbol="NEW", token_ath_mc=900_000),
            CreatedToken(token_address="0xOLD", symbol="OLD", token_ath_mc=1_200_000),
        ],
    )
    prior = [
        t for t in hist.tokens_above_ath(800_000) if t.token_address.lower() != "0xnew"
    ]
    assert len(prior) == 1
    assert prior[0].symbol == "OLD"
