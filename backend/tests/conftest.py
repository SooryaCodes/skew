"""Shared fixtures. No network in any unit test.

Every chain fixture is loaded from the raw REST JSON that Alpaca actually
serves and reconstructed through ``OptionsSnapshot(symbol, raw_data)``, so the
parsers under test see the real schema — including the contracts with no
implied volatility and no bid that a live chain is full of.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from alpaca.data.models.snapshots import OptionsSnapshot

from skew.data.bars import BarSeries, parse_bars
from skew.data.chains import OptionChain, build_chain

FIXTURES = Path(__file__).parent / "fixtures"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def chain_from_fixture(name: str) -> OptionChain:
    """Rebuild an OptionChain from a captured raw response."""
    blob = load_json(name)
    snapshots = {symbol: OptionsSnapshot(symbol, raw) for symbol, raw in blob["snapshots"].items()}
    as_of = datetime.fromisoformat(blob["as_of"])
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)
    return build_chain(
        blob["underlying"],
        float(blob["spot"]),
        snapshots,
        open_interest=blob.get("open_interest"),
        as_of=as_of,
    )


def bars_from_fixture(name: str) -> BarSeries:
    blob = load_json(name)
    return parse_bars(blob["symbol"], blob["bars"])


# ---------------- real captures ----------------


@pytest.fixture(scope="session")
def real_spy_chain() -> OptionChain:
    """A real SPY chain: ~3,900 contracts, several hundred with no IV at all."""
    return chain_from_fixture("chain_spy_real.json")


@pytest.fixture(scope="session")
def real_nvda_chain() -> OptionChain:
    return chain_from_fixture("chain_nvda_real.json")


@pytest.fixture(scope="session")
def real_spy_bars() -> BarSeries:
    return bars_from_fixture("bars_spy_real.json")


@pytest.fixture(scope="session")
def real_nvda_bars() -> BarSeries:
    return bars_from_fixture("bars_nvda_real.json")


# ---------------- synthetic, analytically known ----------------


@pytest.fixture(scope="session")
def calm_chain() -> OptionChain:
    """Contango, normal put skew, ATM 30d IV of 15.8%. Surface is known exactly."""
    return chain_from_fixture("chain_spy.json")


@pytest.fixture(scope="session")
def stressed_chain() -> OptionChain:
    """**Backwardation.** Near-term IV above long-dated — the market is scared.

    Real market data is in contango right now, so a panic cannot be captured;
    this is the fixture that proves the gate which must never let a premium sale
    through actually fires.
    """
    return chain_from_fixture("chain_stressed.json")


@pytest.fixture(scope="session")
def synthetic_bars() -> BarSeries:
    return bars_from_fixture("bars_spy.json")


@pytest.fixture(scope="session")
def known_bars() -> BarSeries:
    """Eleven closes, alternating ±1% in log terms. Volatility computable by hand."""
    return bars_from_fixture("bars_known.json")


@pytest.fixture(scope="session")
def calm_as_of() -> date:
    return datetime.fromisoformat(load_json("chain_spy.json")["as_of"]).date()


@pytest.fixture(scope="session")
def real_as_of() -> date:
    return datetime.fromisoformat(load_json("chain_spy_real.json")["as_of"]).date()


@pytest.fixture(autouse=True, scope="session")
def _no_dotenv_in_tests():
    """Unit tests must never read the developer's real .env.

    Without this, `Settings()` picks up live credentials and a real base URL, so
    assertions about defaults pass or fail depending on whose machine is running
    them. Disabling the env_file makes every Settings() in the suite hermetic.
    """
    from skew.config import Settings

    original = Settings.model_config.get("env_file")
    Settings.model_config["env_file"] = None
    yield
    Settings.model_config["env_file"] = original


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Point every test at its own throwaway SQLite file.

    Without this, a test that writes a decision would pollute the developer's
    real skew.db — and the audit log is append-only by design, so there would be
    no way to clean it up.
    """
    import skew.db as db

    url = f"sqlite:///{tmp_path / 'test.db'}"
    eng = db._make_engine(url)
    monkeypatch.setattr(db, "engine", eng)
    monkeypatch.setattr(db, "SessionLocal", db.sessionmaker(bind=eng, expire_on_commit=False))
    db.Base.metadata.create_all(eng)
    yield
    eng.dispose()
