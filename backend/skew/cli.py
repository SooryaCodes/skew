"""Operator CLI. Every phase's "verify before you stop" step lives here.

    python -m skew.cli scan              # the volatility table across the universe
    python -m skew.cli account           # account, options level, paper assertion
    python -m skew.cli candidates SPY    # structures with gate results and stress grid
    python -m skew.cli poll              # one IV snapshot sample into the store
    python -m skew.cli cycle             # one full loop cycle, dry by default

These print to a terminal, so ``print`` is correct here and ruff is configured
to allow it in this file only.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from skew.config import settings

# ANSI, used sparingly and only where it aids reading a dense table.
DIM = "\033[2m"
BOLD = "\033[1m"
RICH = "\033[38;5;214m"  # amber — vol is expensive
CHEAP = "\033[38;5;74m"  # cool blue — vol is cheap
BREACH = "\033[38;5;167m"  # a gate failed. Nothing else, ever.
RESET = "\033[0m"


def _colour(regime: str) -> str:
    return {"SELL_VOL": RICH, "BUY_VOL": CHEAP}.get(regime, DIM)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)-7s %(name)s: %(message)s",
    )


# ----------------------------------------------------------------------


def cmd_account(_args: argparse.Namespace) -> int:
    from skew.data.broker import Broker

    print(f"{BOLD}SKEW — account check{RESET}")
    print(f"  base url            {settings.alpaca_base_url}")
    print(f"  paper-only assertion {RICH}PASSED{RESET} (import-time, no live code path exists)")

    broker = Broker()
    if not broker.available:
        print(f"  {BREACH}no credentials — set ALPACA_API_KEY / ALPACA_API_SECRET{RESET}")
        return 1

    info = broker.verify_account()
    account = broker.get_account()
    print(f"  account number      {getattr(account, 'account_number', '?')}")
    print(f"  status              {getattr(account, 'status', '?')}")
    print(f"  equity              ${info['equity']:,.2f}")
    print(f"  buying power        ${info['buying_power']:,.2f}")

    level = info["options_approved"]
    ok = level is not None and int(level) >= 3
    mark = f"{RICH}LEVEL {level}{RESET}" if ok else f"{BREACH}LEVEL {level} — need 3{RESET}"
    print(f"  options approval    {mark}")
    if not ok:
        print(f"  {BREACH}Multi-leg spreads require Options Level 3.{RESET}")
        return 1
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    """The volatility table across the universe. Phase 01's verification step."""
    from skew.data.bars import BarClient
    from skew.data.broker import Broker
    from skew.data.chains import ChainClient
    from skew.data.store import history_window_days, iv_series
    from skew.vol.vrp import build_vol_state

    broker = Broker()
    chains = ChainClient(broker)
    bars = BarClient(broker)
    symbols = args.symbols or settings.universe_symbols

    print(f"{BOLD}SKEW — volatility scan{RESET}  {datetime.now(UTC):%Y-%m-%d %H:%M UTC}")
    print(
        f"{DIM}All figures annualised, in vol points. VRP = IV − RV20. TERM is far-minus-near "
        f"ATM IV; nDTE is the nearest expiry on the curve. Direction is not an input.{RESET}\n"
    )
    header = (
        f"{'SYM':<6} {'SPOT':>9} {'IV':>7} {'RV20':>7} {'RVpark':>7} "
        f"{'VRP':>8} {'RV%ile':>7} {'TERM':>8} {'nDTE':>5}  REGIME"
    )
    print(header)
    print("─" * len(header))

    rows = 0
    failures: list[tuple[str, str]] = []
    states = []

    for symbol in symbols:
        try:
            chain = chains.get_chain(
                symbol, dte_min=settings.target_dte_min, dte_max=settings.target_dte_max + 60
            )
            series = bars.get_bars(symbol)
            state = build_vol_state(
                chain,
                series,
                iv_history=iv_series(symbol),
                iv_history_window_days=history_window_days(symbol),
            )
        except Exception as exc:  # noqa: BLE001 — reported per symbol, never silent
            failures.append((symbol, str(exc)))
            print(f"{symbol:<6} {BREACH}{'ABSTAIN — ' + str(exc)[:70]}{RESET}")
            continue

        states.append(state)
        colour = _colour(state.regime)
        near_dte = state.term_curve[0].dte if state.term_curve else 0
        print(
            f"{symbol:<6} {state.spot:>9,.2f} "
            f"{state.iv_atm * 100:>7.1f} {state.rv_20 * 100:>7.1f} "
            f"{state.rv_parkinson * 100:>7.1f} "
            f"{colour}{state.vrp * 100:>+8.1f}{RESET} "
            f"{state.rv_percentile:>7.0f} {state.term_slope * 100:>+8.1f} {near_dte:>5} "
            f" {colour}{state.regime}{RESET}"
        )
        rows += 1

    print()
    for state in states:
        print(f"  {DIM}{state.symbol:<6}{RESET} {state.note}")

    if failures:
        print(f"\n{BREACH}{len(failures)} symbol(s) abstained on data:{RESET}")
        for symbol, why in failures:
            print(f"  {symbol}: {why}")

    # Phase 01's sanity check: if every VRP is negative or every IV is zero,
    # the chain parsing is wrong and nothing above this is trustworthy.
    if rows and all(s.vrp < 0 for s in states):
        print(f"\n{BREACH}WARNING: VRP negative on every name. Check chain parsing.{RESET}")
    if rows and all(s.iv_atm <= 0 for s in states):
        print(f"\n{BREACH}WARNING: ATM IV is zero everywhere. Chain parsing is broken.{RESET}")
    return 0 if rows else 1


def cmd_poll(args: argparse.Namespace) -> int:
    from skew.data.broker import Broker
    from skew.data.chains import ChainClient
    from skew.data.store import IVPoller, history_window_days, observation_count

    broker = Broker()
    poller = IVPoller(ChainClient(broker), args.symbols or settings.universe_symbols)
    stored = poller.poll_once()

    print(f"{BOLD}IV snapshot poll{RESET}  {datetime.now(UTC):%Y-%m-%d %H:%M UTC}")
    print(f"{DIM}Alpaca serves no historical IV. This builds it forward from now.{RESET}\n")
    for symbol, iv in sorted(stored.items()):
        print(
            f"  {symbol:<6} ATM IV {iv * 100:>6.1f}   "
            f"{observation_count(symbol):>4} observations over "
            f"{history_window_days(symbol)} day(s)"
        )
    if not stored:
        print(f"  {BREACH}nothing stored this tick{RESET}")
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    from skew.reporting import print_candidates

    return print_candidates(args.symbol, execute=False)


def cmd_cycle(args: argparse.Namespace) -> int:
    from skew.loop import run_cycle

    report = run_cycle(dry_run=not args.live)
    print(
        f"{BOLD}cycle complete{RESET}  scanned {len(report.scanned)} symbols, "
        f"{len(report.candidates)} candidates, {len(report.decisions)} decisions"
    )
    for d in report.decisions:
        colour = {"EXECUTED": RICH, "REFUSED": BREACH}.get(d.action, DIM)
        print(f"  {colour}{d.action:<10}{RESET} {d.symbol or '—':<6} {d.reason}")
    for err in report.errors:
        print(f"  {BREACH}ERROR{RESET} {err}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skew", description="SKEW volatility desk — operator CLI")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("account", help="verify the paper account and options level").set_defaults(
        func=cmd_account
    )

    p_scan = sub.add_parser("scan", help="volatility table across the universe")
    p_scan.add_argument("symbols", nargs="*", help="defaults to UNIVERSE")
    p_scan.set_defaults(func=cmd_scan)

    p_poll = sub.add_parser("poll", help="store one ATM IV sample per symbol")
    p_poll.add_argument("symbols", nargs="*")
    p_poll.set_defaults(func=cmd_poll)

    p_cand = sub.add_parser("candidates", help="structures, gates and the stress grid")
    p_cand.add_argument("symbol")
    p_cand.set_defaults(func=cmd_candidates)

    p_cycle = sub.add_parser("cycle", help="run one full loop cycle")
    p_cycle.add_argument("--live", action="store_true", help="actually submit an order")
    p_cycle.set_defaults(func=cmd_cycle)

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    # Every command touches the store at some point — the IV history read in
    # `scan` included. Create tables once, here, rather than in each command.
    from skew.db import init_db

    init_db()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
