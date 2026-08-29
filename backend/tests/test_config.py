"""The paper-only guarantee is the project's central safety claim. Test it hard."""

import pytest

from skew.config import PAPER_HOST, PaperOnlyViolation, Settings, assert_paper_only


def test_default_base_url_is_the_paper_endpoint():
    assert Settings().alpaca_base_url == PAPER_HOST


@pytest.mark.parametrize(
    "live_url",
    [
        "https://api.alpaca.markets",
        "https://API.ALPACA.MARKETS",
        "https://broker-api.alpaca.markets",
        "http://localhost:9999",
        "",
    ],
)
def test_settings_refuse_any_non_paper_url(live_url):
    with pytest.raises(PaperOnlyViolation):
        Settings(alpaca_base_url=live_url)


def test_assert_paper_only_guard():
    assert_paper_only(PAPER_HOST)  # does not raise
    with pytest.raises(PaperOnlyViolation):
        assert_paper_only("https://api.alpaca.markets")
    with pytest.raises(PaperOnlyViolation):
        assert_paper_only(None)


def test_paper_url_is_normalised():
    assert Settings(alpaca_base_url=PAPER_HOST + "/").alpaca_base_url == PAPER_HOST


def test_redacted_never_emits_a_credential():
    # Deliberately not key-shaped. A secret scanner run over this repo should
    # find nothing that even looks like a credential, including in the tests.
    s = Settings(
        alpaca_api_key="NOT-A-REAL-KEY-fixture-only",
        alpaca_api_secret="NOT-A-REAL-SECRET-fixture-only",
        anthropic_api_key="NOT-A-REAL-ANTHROPIC-KEY-fixture-only",
        admin_token="NOT-A-REAL-TOKEN-fixture-only",
    )
    blob = repr(s.redacted())
    for secret in (
        "NOT-A-REAL-KEY-fixture-only",
        "NOT-A-REAL-SECRET-fixture-only",
        "NOT-A-REAL-ANTHROPIC-KEY-fixture-only",
        "NOT-A-REAL-TOKEN-fixture-only",
    ):
        assert secret not in blob
    assert s.redacted()["alpaca_api_key"] == "***set***"
    assert Settings().redacted()["alpaca_api_key"] == "***unset***"


def test_regime_bands_must_leave_an_abstain_window():
    with pytest.raises(Exception, match="ABSTAIN"):
        Settings(vrp_sell_floor=1.0, vrp_buy_ceiling=2.0)


def test_universe_parsing():
    assert Settings(universe=" spy , qqq,, iwm ").universe_symbols == ["SPY", "QQQ", "IWM"]
