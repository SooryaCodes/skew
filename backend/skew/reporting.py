"""Terminal rendering for the operator CLI.

Kept out of ``cli.py`` so the formatting of a candidate — legs, risk numbers,
gate chain, stress grid — exists in one place and is reused by ``candidates``,
``cycle`` and the dry-run reports.

The ASCII stress grid here is the terminal twin of the 7×4 heatmap in the
dashboard, and it is what the Phase 03 verification step reads.
"""

from __future__ import annotations

from skew.models import Candidate, Structure

DIM = "\033[2m"
BOLD = "\033[1m"
RICH = "\033[38;5;214m"
CHEAP = "\033[38;5;74m"
BREACH = "\033[38;5;167m"
GREY = "\033[38;5;245m"
RESET = "\033[0m"


def money(value: float) -> str:
    """Always signed, always two decimals. Matches the UI's number rules."""
    return f"{'-' if value < 0 else '+'}${abs(value):,.2f}"


def render_structure(s: Structure) -> list[str]:
    """The legs and the risk numbers for one structure."""
    lines = [
        f"{BOLD}{s.kind.replace('_', ' ').title()}{RESET}  {s.symbol}  "
        f"{DIM}{s.dte}d to expiry{RESET}",
        f"  {DIM}id{RESET} {s.id}",
    ]
    for leg in sorted(s.legs, key=lambda x: (x.right, x.strike)):
        arrow = "SELL" if leg.side == "SELL" else "BUY "
        colour = RICH if leg.side == "SELL" else CHEAP
        lines.append(
            f"  {colour}{arrow}{RESET} {leg.ratio_qty}x {leg.symbol:<22} "
            f"{leg.strike:>8,.2f} {leg.right:<4} "
            f"@ {leg.mid:>6.2f}  {DIM}iv {leg.iv * 100:>5.1f}  Δ {leg.delta:>+6.3f}  "
            f"oi {leg.open_interest:>6,}{RESET}"
        )

    kind = "credit" if s.is_credit else "debit"
    lines += [
        f"  {DIM}net {kind:<7}{RESET} {money(s.net_credit)}"
        f"      {DIM}max loss{RESET} {BOLD}${s.max_loss:,.2f}{RESET}"
        f"      {DIM}max profit{RESET} ${s.max_profit:,.2f}",
        f"  {DIM}breakeven{RESET}   "
        + " / ".join(f"{b:,.2f}" for b in s.breakevens)
        + f"      {DIM}width{RESET} {s.width:g}"
        + f"      {DIM}limit{RESET} {s.limit_price:+.2f} "
        + f"{DIM}({'credit' if s.limit_price < 0 else 'debit'}){RESET}",
        f"  {DIM}net greeks{RESET}  Δ {s.net_delta:>+8.2f}   "
        f"vega {s.net_vega:>+8.2f}   theta {s.net_theta:>+8.2f}   "
        f"gamma {s.net_gamma:>+8.4f}",
    ]
    return lines


def render_gates(candidate: Candidate) -> list[str]:
    """One row per gate: name, glyph, and the reason string verbatim.

    The reason is written in the backend and rendered here and in the UI without
    rewording, so it has to read as human copy with real numbers in it.
    """
    lines = [f"  {DIM}gates{RESET}"]
    for gate in candidate.gates:
        if gate.skipped:
            glyph, colour = "—", GREY
        elif gate.passed:
            glyph, colour = "✓", CHEAP
        else:
            glyph, colour = "✗", BREACH
        lines.append(f"    {colour}{glyph}{RESET} {gate.gate:<14} {colour}{gate.reason}{RESET}")
    return lines


def render_stress_grid(candidate: Candidate, time_point: str = "MID") -> list[str]:
    """The 7×4 grid for one time slice, worst cell marked.

    Price shocks across, IV shocks down. A breaching cell is the only thing on
    this screen that is allowed to be red.
    """
    cells = [c for c in candidate.stress_grid if c.time_point == time_point]
    if not cells:
        return [f"  {DIM}no stress grid{RESET}"]

    price_shocks = sorted({c.price_shock for c in cells})
    iv_shocks = sorted({c.iv_shock for c in cells})
    lookup = {(c.price_shock, c.iv_shock): c for c in cells}
    worst = min(cells, key=lambda c: c.pnl)

    header = "IV / px".rjust(8) + " " + " ".join(f"{p:>+8.0f}s" for p in price_shocks)
    lines = [
        f"  {DIM}stress grid — {time_point.lower()}, price shock across, IV shock down{RESET}",
        f"    {DIM}{header}{RESET}",
    ]

    for iv in iv_shocks:
        row = [f"    {f'x{iv:.1f}':>8} "]
        for px in price_shocks:
            cell = lookup.get((px, iv))
            if cell is None:
                row.append(f"{'—':>9}")
                continue
            text = f"{cell.pnl:>+9,.0f}"
            if cell.breached:
                row.append(f"{BREACH}{text}{RESET}")
            elif cell is worst:
                row.append(f"{BOLD}{text}{RESET}")
            else:
                row.append(text)
        lines.append("".join(row))

    marker = f"{BREACH}BREACH{RESET}" if worst.breached else f"{DIM}within budget{RESET}"
    lines.append(
        f"    {DIM}worst cell{RESET} {worst.pnl:+,.0f} at {worst.price_shock:+.0f}σ "
        f"with IV x{worst.iv_shock:.1f} — {marker}"
    )
    return lines


def render_candidate(candidate: Candidate, grid_time: str = "MID") -> list[str]:
    lines = render_structure(candidate.structure)
    lines += render_gates(candidate)
    lines += render_stress_grid(candidate, grid_time)

    if candidate.passed_all:
        lines.append(f"  {CHEAP}PASSED all gates{RESET}")
    else:
        failed = ", ".join(g.gate for g in candidate.failed_gates)
        lines.append(f"  {BREACH}REFUSED — failed: {failed or 'unknown'}{RESET}")
    return lines


def print_candidates(symbol: str, execute: bool = False) -> int:
    """Build, gate and stress-test live candidates for one symbol, then print.

    This is the Phase 02 and Phase 03 verification step. ``execute`` is accepted
    for symmetry with the loop but ignored — this path never submits an order.
    """
    from skew.desk import Desk

    desk = Desk()
    result = desk.evaluate_symbol(symbol.upper())

    print(f"{BOLD}SKEW — candidates for {symbol.upper()}{RESET}")
    if result.vol_state is None:
        print(f"  {BREACH}{result.error or 'no volatility state'}{RESET}")
        return 1

    v = result.vol_state
    colour = {"SELL_VOL": RICH, "BUY_VOL": CHEAP}.get(v.regime, DIM)
    print(
        f"  spot {v.spot:,.2f}   IV {v.iv_atm * 100:.1f}   RV20 {v.rv_20 * 100:.1f}   "
        f"{colour}VRP {v.vrp * 100:+.1f}{RESET}   term {v.term_slope * 100:+.1f}   "
        f"{colour}{v.regime}{RESET}"
    )
    print(f"  {DIM}{v.note}{RESET}")
    print(
        f"  {DIM}risk tier {result.risk.tier} — budget ${result.risk.budget_dollars:,.0f} "
        f"per trade ({result.risk.max_loss_pct:.1%} of ${result.risk.equity:,.0f}){RESET}\n"
    )

    if not result.candidates:
        print(
            f"  {DIM}No candidates — {result.error or 'nothing constructible from this chain'}"
            f"{RESET}"
        )
        return 0

    for candidate in result.candidates:
        for line in render_candidate(candidate):
            print(line)
        print()

    survivors = [c for c in result.candidates if c.passed_all]
    print(
        f"{BOLD}{len(survivors)} of {len(result.candidates)} candidates survived the gate chain."
        f"{RESET}"
    )
    if not survivors:
        print(
            f"{DIM}Refusals are logged as prominently as executions — that is the product.{RESET}"
        )
    return 0
