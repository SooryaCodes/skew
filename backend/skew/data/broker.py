"""The single seam between SKEW and Alpaca.

Addition to the module map in docs/01-ARCHITECTURE.md §1, and a deliberate one:
every network call to Alpaca goes through this class and nothing else in the
codebase constructs a client. That buys three things —

1. The paper-only assertion runs in exactly one place, immediately before any
   client is built, so there is no path to a live endpoint even by accident.
2. The rest of the system takes a ``Broker`` by injection, so every module above
   this one is testable with no network and no credentials.
3. Credentials exist in one file and are never logged, not even partially.

Note the chain/open-interest split described in ``chains.py``: implied
volatility and Greeks come from the *data* API snapshot, open interest from the
*trading* API contract record.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from skew.config import Settings, assert_paper_only
from skew.config import settings as default_settings

log = logging.getLogger(__name__)


class BrokerUnavailable(RuntimeError):
    """Raised when credentials are absent. Never carries a credential value."""


class Broker:
    """Thin, typed wrapper over the Alpaca SDK clients."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or default_settings
        # Belt and braces. The field validator already refused a non-paper URL;
        # this is the check that runs immediately before a client exists.
        assert_paper_only(self.settings.alpaca_base_url)
        self._trading: Any = None
        self._option_data: Any = None
        self._stock_data: Any = None

    # ------------------------------------------------------------------
    # Client construction — lazy, so importing this module needs no keys
    # ------------------------------------------------------------------

    def _require_credentials(self) -> None:
        if not self.settings.has_broker_credentials:
            raise BrokerUnavailable(
                "ALPACA_API_KEY and ALPACA_API_SECRET are not set. SKEW will not "
                "guess at market data — set them in .env and restart."
            )

    @property
    def trading(self) -> Any:
        if self._trading is None:
            self._require_credentials()
            assert_paper_only(self.settings.alpaca_base_url)
            from alpaca.trading.client import TradingClient

            self._trading = TradingClient(
                api_key=self.settings.alpaca_api_key,
                secret_key=self.settings.alpaca_api_secret,
                paper=True,  # not configurable. There is no live path.
            )
        return self._trading

    @property
    def option_data(self) -> Any:
        if self._option_data is None:
            self._require_credentials()
            from alpaca.data.historical.option import OptionHistoricalDataClient

            self._option_data = OptionHistoricalDataClient(
                api_key=self.settings.alpaca_api_key,
                secret_key=self.settings.alpaca_api_secret,
            )
        return self._option_data

    @property
    def stock_data(self) -> Any:
        if self._stock_data is None:
            self._require_credentials()
            from alpaca.data.historical.stock import StockHistoricalDataClient

            self._stock_data = StockHistoricalDataClient(
                api_key=self.settings.alpaca_api_key,
                secret_key=self.settings.alpaca_api_secret,
            )
        return self._stock_data

    @property
    def available(self) -> bool:
        return self.settings.has_broker_credentials

    # ------------------------------------------------------------------
    # Account
    # ------------------------------------------------------------------

    def get_account(self) -> Any:
        return self.trading.get_account()

    def verify_account(self) -> dict[str, Any]:
        """Startup check per docs/05-SECURITY.md.

        Confirms the account is the dedicated hackathon account when an account
        number is configured, and warns when equity is not roughly $100k. Warns
        rather than refuses on equity: a paper balance drifting is normal, a
        wrong *account* is not.
        """
        account = self.get_account()
        number = str(getattr(account, "account_number", "") or "")
        equity = float(getattr(account, "equity", 0.0) or 0.0)

        expected = self.settings.alpaca_account_number
        if expected and number != expected:
            raise RuntimeError(
                "Connected account does not match ALPACA_ACCOUNT_NUMBER. Refusing "
                "to trade an account this desk does not own."
            )
        if expected == "":
            log.warning(
                "ALPACA_ACCOUNT_NUMBER is unset — cannot verify this is the dedicated "
                "hackathon account. Set it before the demo."
            )

        target = self.settings.expected_equity
        if target > 0 and abs(equity - target) / target > 0.25:
            log.warning(
                "Account equity %.2f is more than 25%% away from the expected %.2f. "
                "Check this is the right paper account.",
                equity,
                target,
            )
        return {
            "account_number_set": bool(expected),
            "equity": equity,
            "buying_power": float(getattr(account, "buying_power", 0.0) or 0.0),
            "options_level": getattr(account, "options_trading_level", None),
            "options_approved": getattr(account, "options_approved_level", None),
        }

    # ------------------------------------------------------------------
    # Market data
    # ------------------------------------------------------------------

    def fetch_spot(self, symbol: str) -> float:
        """Latest trade price for the underlying.

        Falls back to the latest quote mid when no trade has printed (thin
        pre-market tape), and returns 0.0 when neither is usable so the caller
        abstains loudly rather than pricing off a zero.
        """
        from alpaca.data.requests import StockLatestQuoteRequest, StockLatestTradeRequest

        try:
            trades = self.stock_data.get_stock_latest_trade(
                StockLatestTradeRequest(symbol_or_symbols=symbol)
            )
            price = float(getattr(trades.get(symbol), "price", 0.0) or 0.0)
            if price > 0:
                return price
        except Exception as exc:
            log.warning("latest trade unavailable for %s: %s", symbol, exc)

        quotes = self.stock_data.get_stock_latest_quote(
            StockLatestQuoteRequest(symbol_or_symbols=symbol)
        )
        q = quotes.get(symbol)
        bid = float(getattr(q, "bid_price", 0.0) or 0.0)
        ask = float(getattr(q, "ask_price", 0.0) or 0.0)
        return (bid + ask) / 2.0 if bid > 0 and ask > 0 else 0.0

    def fetch_option_chain(
        self,
        symbol: str,
        expiry_gte: date | None = None,
        expiry_lte: date | None = None,
        strike_gte: float | None = None,
        strike_lte: float | None = None,
    ) -> dict[str, Any]:
        """Raw ``{contract_symbol: OptionsSnapshot}``.

        The snapshot carries implied volatility and Greeks — we never invert
        Black-Scholes to get them.
        """
        from alpaca.data.requests import OptionChainRequest

        request = OptionChainRequest(
            underlying_symbol=symbol,
            expiration_date_gte=expiry_gte,
            expiration_date_lte=expiry_lte,
            strike_price_gte=str(round(strike_gte, 2)) if strike_gte else None,
            strike_price_lte=str(round(strike_lte, 2)) if strike_lte else None,
        )
        return dict(self.option_data.get_option_chain(request))

    def fetch_open_interest(
        self, symbol: str, expiries: list[date] | None = None
    ) -> dict[str, int]:
        """Contract symbol -> open interest, from the *trading* API.

        Open interest is not on the data-API snapshot; see the module docstring
        in ``chains.py``. Paginated, and capped so a bad expiry filter cannot
        walk the entire options universe.
        """
        from alpaca.trading.requests import GetOptionContractsRequest

        out: dict[str, int] = {}
        expiry_lte = max(expiries) if expiries else None
        expiry_gte = min(expiries) if expiries else None
        page_token: str | None = None

        for _ in range(20):  # hard page cap
            request = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                expiration_date_gte=expiry_gte,
                expiration_date_lte=expiry_lte,
                limit=10_000,
                page_token=page_token,
            )
            response = self.trading.get_option_contracts(request)
            contracts = getattr(response, "option_contracts", None) or []
            for contract in contracts:
                oi = getattr(contract, "open_interest", None)
                if oi is not None:
                    out[str(contract.symbol).upper()] = int(oi)
            page_token = getattr(response, "next_page_token", None)
            if not page_token:
                break
        return out

    def fetch_daily_bars(self, symbol: str, lookback_days: int = 380) -> list[dict[str, Any]]:
        """Daily OHLCV for the underlying, oldest first.

        Asks for 380 calendar days to reliably yield 252 trading days.
        """
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame

        end = datetime.now(UTC)
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame.Day,
            start=end - timedelta(days=lookback_days),
            end=end,
            feed="iex",
        )
        barset = self.stock_data.get_stock_bars(request)
        rows = barset.data.get(symbol, []) if hasattr(barset, "data") else []
        return [
            {
                "date": b.timestamp.date() if hasattr(b.timestamp, "date") else b.timestamp,
                "open": float(b.open),
                "high": float(b.high),
                "low": float(b.low),
                "close": float(b.close),
                "volume": float(b.volume or 0),
            }
            for b in rows
        ]

    # ------------------------------------------------------------------
    # Clock and calendar
    # ------------------------------------------------------------------

    def get_clock(self) -> Any:
        return self.trading.get_clock()

    def is_market_open(self) -> bool:
        return bool(getattr(self.get_clock(), "is_open", False))

    # ------------------------------------------------------------------
    # Orders and positions
    # ------------------------------------------------------------------

    def submit_order(self, order_request: Any) -> Any:
        assert_paper_only(self.settings.alpaca_base_url)
        return self.trading.submit_order(order_request)

    def get_order_by_client_id(self, client_order_id: str) -> Any:
        return self.trading.get_order_by_client_id(client_order_id)

    def list_positions(self) -> list[Any]:
        return list(self.trading.get_all_positions())

    def list_orders(self, request: Any) -> list[Any]:
        return list(self.trading.get_orders(request))
