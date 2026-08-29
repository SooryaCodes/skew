"""Serialising candidates for the bounded selector.

Everything the model sees is built here, and nothing else reaches it. The block
below is the model's entire world: a numbered list of pre-validated structures,
the volatility state that produced them, and each one's worst case. No account
data, no keys, no tools, no execution function, no market data it could act on
independently.

Two rules shape the format:

* **Only facts the risk engine has already validated.** Every candidate in the
  block passed all five gates. The model is not being asked whether a trade is
  safe — that question is settled before it is called — only which of several
  safe trades best expresses the volatility signal, or none.
* **No free text from outside the system.** Contract symbols, strikes and
  numbers come from Alpaca and from our own arithmetic. Nothing user-supplied is
  interpolated, so the prompt-injection surface is close to zero. That is a
  property worth preserving: if a data source that carries free text is ever
  added, it must be escaped or excluded here.
"""

from __future__ import annotations

from skew.models import Candidate, RiskAuthority, VolState

SYSTEM_PROMPT = """\
You are the selection step of an autonomous options volatility desk called SKEW.

The desk trades the variance risk premium: the gap between implied volatility \
and subsequently realized volatility. It has no view on price direction, and \
neither do you. Never reason about where the underlying is going.

Every candidate you are shown has already passed a deterministic gate chain — \
liquidity, earnings, term structure, a stress test across 84 scenarios, and the \
risk budget. Safety is settled before you are called. Your only job is to pick \
the candidate that best expresses the measured volatility signal, or to abstain.

Choose based on:
- how well the structure matches the regime (short premium when IV is rich, \
long premium when it is cheap)
- credit received relative to maximum loss
- how much of the max loss an ordinary move already reaches
- net vega: this desk expresses a volatility view, so vega is the exposure that \
should carry the position, not delta

Abstain when no candidate is a good expression of the signal. Abstaining is a \
normal, respected outcome and is logged as prominently as a trade. A weak trade \
is worse than no trade.

Reply with JSON only, no prose around it, in exactly this shape:

{"candidate_id": "<one id from the list, or null to abstain>",
 "rationale": "<one or two sentences>"}

The rationale must reference the volatility signal. It is displayed to a human \
and stored permanently. You cannot modify a structure, change a strike, alter a \
quantity, or request anything not on the list; any other output is treated as \
an abstention."""


def format_vol_state(vol: VolState) -> str:
    """The volatility picture, in vol points for readability."""
    shape = "contango" if vol.term_slope > 0 else "backwardation" if vol.term_slope < 0 else "flat"
    lines = [
        f"Symbol           {vol.symbol}",
        f"Spot             {vol.spot:,.2f}",
        f"ATM implied vol  {vol.iv_atm * 100:.1f}",
        f"Realized vol 20d {vol.rv_20 * 100:.1f}  (Parkinson {vol.rv_parkinson * 100:.1f})",
        f"VRP              {vol.vrp * 100:+.1f} vol points  <- the signal",
        f"Realized-vol percentile  {vol.rv_percentile:.0f} over its own trailing distribution",
        f"Term structure   {vol.term_slope * 100:+.1f} vol points far minus near ({shape})",
        f"Regime           {vol.regime}",
    ]
    if vol.iv_rank is not None:
        lines.append(
            f"IV rank          {vol.iv_rank:.0f} over {vol.iv_rank_window_days} day(s) of "
            f"self-collected history (NOT a 52-week rank — Alpaca serves no historical IV)"
        )
    else:
        lines.append(
            "IV rank          unavailable — Alpaca serves no historical IV and we have not "
            "yet accumulated enough of our own"
        )
    return "\n".join(lines)


def format_candidate(index: int, candidate: Candidate) -> str:
    """One candidate: what it is, what it costs, and what it risks."""
    s = candidate.structure
    legs = "\n".join(
        f"      {leg.side:<4} {leg.ratio_qty}x {leg.symbol}  strike {leg.strike:g} "
        f"{leg.right}  mid {leg.mid:.2f}  delta {leg.delta:+.3f}"
        for leg in sorted(s.legs, key=lambda x: (x.right, x.strike))
    )

    routine = ""
    for gate in candidate.gates:
        if gate.gate == "stress" and gate.detail.get("routine_pnl") is not None:
            routine_pnl = abs(float(gate.detail["routine_pnl"]))
            pct = routine_pnl / s.max_loss if s.max_loss else 0.0
            routine = (
                f"\n      routine 1-sigma move loses ${routine_pnl:,.0f} ({pct:.0%} of max loss)"
            )
            break

    kind_word = "credit" if s.is_credit else "debit"
    return f"""\
  [{index}] id: {s.id}
      structure    {s.kind.replace("_", " ").lower()}, {s.dte} days to expiry
{legs}
      net {kind_word:<7}  ${abs(s.net_credit):,.2f}
      max loss     ${s.max_loss:,.2f}
      max profit   ${s.max_profit:,.2f}
      breakevens   {" / ".join(f"{b:,.2f}" for b in s.breakevens)}
      net vega     {s.net_vega:+.2f}   net theta {s.net_theta:+.2f}   \
net delta {s.net_delta:+.2f}
      worst case across all 84 stress scenarios: ${candidate.worst_case:,.2f}{routine}"""


def build_user_message(
    vol: VolState,
    candidates: list[Candidate],
    risk: RiskAuthority,
) -> str:
    """The complete message. This, plus the system prompt, is all the model sees."""
    blocks = "\n\n".join(format_candidate(i + 1, c) for i, c in enumerate(candidates))
    ids = ", ".join(f'"{c.id}"' for c in candidates)

    return f"""\
VOLATILITY STATE
{format_vol_state(vol)}

RISK AUTHORITY
Tier {risk.tier} — max loss ${risk.budget_dollars:,.0f} per trade \
({risk.max_loss_pct:.1%} of ${risk.equity:,.0f} equity)
${risk.available_dollars:,.0f} of that budget is still uncommitted.
{risk.open_positions} of {risk.max_concurrent_positions} concurrent positions are open.

CANDIDATES — all have passed every gate
{blocks}

Select one candidate id from [{ids}], or null to abstain.
Reply with JSON only."""


def estimate_tokens(text: str) -> int:
    """Rough size check, so an oversized prompt is caught before it is sent."""
    return len(text) // 4
