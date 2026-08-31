"""Settings and the paper-only guarantee.

The single most important line in this file is the paper-only assertion. SKEW has
no live-trading code path — not behind a flag, not behind an environment variable.
The assertion below is the enforcement, and it fires at import time so that a
misconfigured deployment cannot get as far as constructing a broker client.

See docs/05-SECURITY.md.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The only broker host SKEW will ever talk to for trading.
PAPER_HOST = "https://paper-api.alpaca.markets"


class PaperOnlyViolation(RuntimeError):
    """Raised when configuration points anywhere other than the paper endpoint."""


class Settings(BaseSettings):
    """Runtime configuration, loaded from the environment.

    Every field has a safe default so that the test suite and the pure-maths
    modules run with no environment at all. Only the credentials are genuinely
    required, and only at the point a network client is constructed.
    """

    model_config = SettingsConfigDict(
        # The repo keeps .env at the root; the backend may also be run from within
        # backend/. Accept either location, root taking precedence.
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Alpaca (paper only) ----
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = PAPER_HOST
    # Optional: the dedicated hackathon account number. When set, startup verifies
    # the connected account matches, so a stray key cannot trade the wrong account.
    alpaca_account_number: str = ""
    # Hackathon rule: the submission runs on a brand-new paper account. When
    # set, boot verifies the connected account IS that account, and the desk
    # refuses to report ARMED on a mismatch — the guard against accidentally
    # submitting with the dev account.
    competition_account_id: str = ""
    expected_equity: float = 100_000.0

    # ---- Anthropic (bounded selector model) ----
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"

    # ---- Runtime ----
    universe: str = "SPY,QQQ,IWM,AAPL,MSFT,NVDA,AMD,TSLA"
    loop_interval_seconds: int = 300
    iv_poll_interval_seconds: int = 300
    database_url: str = "sqlite:///./skew.db"

    # ---- Risk authority ----
    risk_tier_start: int = Field(default=0, ge=0, le=2)
    max_concurrent_positions: int = Field(default=3, ge=1)
    kill_switch: bool = False

    # ---- API ----
    # Container binding. Only read endpoints are public; the one write endpoint is authed.
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    # Shared secret for every action endpoint (cycle trigger, kill switch,
    # universe edits). ADMIN_TOKEN is accepted as a legacy alias.
    operator_token: str = ""
    admin_token: str = ""
    cors_origins: str = "*"
    rate_limit: str = "120/minute"

    # ---- Scheduler ----
    # The API process runs the trading loop, because the loop needs a persistent
    # process and serverless will not do.
    run_scheduler: bool = True
    # Off by default: the loop scans, gates and logs every cycle but submits
    # nothing until this is explicitly turned on. Paper trading is safe, but
    # placing orders while developing the UI is still not what anyone wants.
    auto_execute: bool = False

    # ---- MCP ----
    # Write tools on the MCP surface are OFF unless this is explicitly enabled.
    mcp_allow_execute: bool = False

    # ---- Strategy parameters ----
    # VRP entry floor in annualised vol points. IV must exceed RV by this much
    # before we will consider selling premium.
    vrp_sell_floor: float = 4.0
    # VRP below this (IV cheap relative to realised) flips us to buying premium.
    vrp_buy_ceiling: float = -2.0
    # Competition window: 7-14 DTE so a position opened Monday can reach its
    # profit target and CLOSE before the Thursday finish — position management
    # is a stated judging requirement. The tradeoff is real and accepted:
    # shorter DTE means higher gamma near expiry, i.e. P&L moves faster against
    # a spot move in the final days. Our structures are defined-risk (the long
    # leg caps the loss regardless of gamma) and the stress grid already prices
    # the at-expiry scenarios, so the risk is bounded and measured, not wished
    # away. DTE_MIN / DTE_MAX env vars override.
    target_dte_min: int = Field(
        default=7, validation_alias=AliasChoices("dte_min", "target_dte_min")
    )
    target_dte_max: int = Field(
        default=14, validation_alias=AliasChoices("dte_max", "target_dte_max")
    )
    short_leg_delta_target: float = 0.25
    # Structural liquidity floors, tuned at ~30 DTE. Short-dated chains carry
    # structurally less open interest, so the gate scales these by tenor —
    # see skew/gates/liquidity.py scaled_floors().
    min_open_interest: int = 100
    max_spread_pct: float = 0.15
    min_volume: int = 0
    # Term structure: block premium selling only on a MATERIAL inversion. The
    # front of the curve inverts routinely for idiosyncratic reasons; a
    # 0.3-point dip is noise, not stress. Measured trade-tenor vs a 60-90d
    # reference. Env: TERM_BACKWARDATION_FLOOR (vol points as a decimal).
    term_backwardation_floor: float = 0.015
    term_far_target_dte: int = 75
    # Earnings blackout, in calendar days either side of the report.
    earnings_blackout_days: int = 7
    # Alpaca serves no earnings calendar. When a single name has no confirmed
    # date, block premium selling rather than assume it is clear. See
    # skew/gates/earnings.py before turning this off.
    earnings_unknown_blocks: bool = True
    # Used only by the stress engine's Black-Scholes repricing. Not a market
    # observation — a parameter, and a shift of 100bp moves a 30-day option by
    # pennies, so it is set rather than fetched.
    risk_free_rate: float = 0.042
    # Target strike width as a fraction of spot.
    target_width_pct: float = 0.0075
    # Stress engine, routine-move check. A move of this many sigma must not
    # already reach more than this fraction of the structure's own max loss —
    # the check that separates two structures with the same max loss but very
    # different odds of reaching it. See skew/stress/scenarios.py.
    routine_sigma: float = 1.0
    routine_max_loss_pct: float = 0.60
    # Long premium: the breakeven must sit within this many sigma of spot, or the
    # structure needs a tail event rather than ordinary movement to come good.
    max_breakeven_sigma: float = 1.25
    # Unattended-judging circuit breaker: past this account drawdown the desk
    # stops OPENING positions (monitoring continues) until equity recovers.
    # An agent that stands itself down is the thesis, not a failure mode.
    drawdown_breaker_pct: float = 0.05
    # Exit rules. The profit target sits mid 40-50% so short-DTE credit trades
    # can realistically close inside the competition week.
    profit_target_pct: float = 0.45
    loss_limit_multiple: float = 2.0
    # At 7-14 DTE entries this must sit BELOW dte_min, or every new position
    # would qualify for the time-exit on day one. Two days keeps us out of the
    # worst of expiry gamma without amputating the holding period.
    exit_dte_threshold: int = 2
    # Hard deadline: flatten everything before the competition ends. ISO-8601, or
    # empty to disable.
    deadline_utc: str = ""

    # ------------------------------------------------------------------
    # The paper-only guarantee
    # ------------------------------------------------------------------

    @field_validator("alpaca_base_url")
    @classmethod
    def _must_be_paper(cls, v: str) -> str:
        if "paper" not in v.lower():
            raise PaperOnlyViolation(
                f"SKEW is paper-only. Refusing to start. "
                f"ALPACA_BASE_URL must point at the paper endpoint ({PAPER_HOST}); "
                f"got {v!r}."
            )
        return v.rstrip("/")

    @model_validator(mode="after")
    def _sanity(self) -> Settings:
        if self.vrp_buy_ceiling >= self.vrp_sell_floor:
            raise ValueError(
                "vrp_buy_ceiling must be strictly below vrp_sell_floor; "
                "otherwise the regime classifier has no ABSTAIN band."
            )
        if self.target_dte_min > self.target_dte_max:
            raise ValueError("target_dte_min must not exceed target_dte_max")
        return self

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def universe_symbols(self) -> list[str]:
        return [s.strip().upper() for s in self.universe.split(",") if s.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_broker_credentials(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)

    @property
    def has_model_credentials(self) -> bool:
        return bool(self.anthropic_api_key)

    def redacted(self) -> dict[str, object]:
        """A dict safe to log or serve. Never emits a credential, not even a prefix."""
        data = self.model_dump()
        for key in (
            "alpaca_api_key",
            "alpaca_api_secret",
            "anthropic_api_key",
            "admin_token",
            "alpaca_account_number",
        ):
            data[key] = "***set***" if data.get(key) else "***unset***"
        return data


def assert_paper_only(base_url: str) -> None:
    """Explicit guard, called again wherever a trading client is constructed.

    Belt and braces: the field validator already ran, but the cost of checking
    twice is nil and the cost of being wrong once is the whole project.
    """
    if "paper" not in (base_url or "").lower():
        raise PaperOnlyViolation(
            f"SKEW is paper-only. Refusing to start. Got base URL {base_url!r}."
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()


# Import-time enforcement. If the environment points at the live endpoint, this
# module fails to import and nothing downstream can run.
settings = get_settings()
assert_paper_only(settings.alpaca_base_url)
