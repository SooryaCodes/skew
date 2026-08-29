"""The bounded selector — an untrusted component, treated as one.

docs/05-SECURITY.md, "The model is not trusted". Everything in this file exists
to make one sentence true: **the model cannot place a trade; it can only choose
among trades the risk engine already approved.**

Concretely, and enforced in code rather than asked for in the prompt:

* It receives a serialised list of pre-validated candidates and nothing else.
  No account access, no API keys, no tools, no execution function.
* Its response is parsed and validated against a strict schema. It must name one
  of the candidate IDs it was given, or abstain.
* An ID that was not on the list -> **abstention**, logged as malformed.
* Malformed JSON, an empty response, a timeout, an API error -> **abstention**.
* An empty candidate list -> abstention **without calling the model at all**.
* The rationale is stored and displayed. It is never parsed for instructions,
  never evaluated, and nothing it contains can change what executes.

The failure mode this design rules out is the one that matters: there is no
string the model can emit that causes anything to happen other than one of the
N+1 outcomes the risk engine already sanctioned.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from skew.agent.prompt import SYSTEM_PROMPT, build_user_message
from skew.config import Settings
from skew.config import settings as default_settings
from skew.models import Candidate, ModelSelection, RiskAuthority, VolState

log = logging.getLogger(__name__)

MAX_TOKENS = 400
MAX_RATIONALE_CHARS = 600
# Long enough for a slow response, short enough that a hung API cannot stall the
# trading loop past its next tick.
TIMEOUT_SECONDS = 30.0


def _abstain(reason: str, malformed: bool = False) -> ModelSelection:
    return ModelSelection(candidate_id=None, rationale=reason, abstained=True, malformed=malformed)


def _clean_rationale(text: Any) -> str:
    """Sanitise the model's free text for storage and display.

    Never parsed for instructions — this only makes it safe to *render*.
    Control characters are stripped, length is capped, and the result is stored
    as data. Nothing downstream branches on its contents.
    """
    if not isinstance(text, str):
        return ""
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()
    if len(cleaned) > MAX_RATIONALE_CHARS:
        cleaned = cleaned[: MAX_RATIONALE_CHARS - 1].rstrip() + "…"
    return cleaned


def extract_json(raw: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a response.

    Tolerant of a fenced code block or a sentence of preamble, because those are
    formatting noise rather than boundary violations. Not tolerant of anything
    that is not a JSON object — that returns None and becomes an abstention.
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            return None
        text = text[start : end + 1]

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def validate_selection(raw: str, allowed_ids: list[str]) -> ModelSelection:
    """Turn a raw response into one of exactly two outcomes: a valid ID, or abstain.

    Pure and network-free, so every boundary violation is testable without an
    API key. This is the function that makes the security claim true.
    """
    payload = extract_json(raw)
    if payload is None:
        log.warning("bounded selector returned unparseable output; treating as abstention")
        return _abstain(
            "Model returned malformed output. Treated as an abstention.", malformed=True
        )

    rationale = _clean_rationale(payload.get("rationale"))
    chosen = payload.get("candidate_id")

    if chosen is None:
        return ModelSelection(
            candidate_id=None,
            rationale=rationale or "Model abstained without a stated reason.",
            abstained=True,
            malformed=False,
        )

    if not isinstance(chosen, str):
        log.warning("bounded selector returned a non-string candidate_id: %r", type(chosen))
        return _abstain(
            "Model returned a candidate_id that was not a string. Treated as an abstention.",
            malformed=True,
        )

    if chosen not in allowed_ids:
        # The important one. The model named something it was not offered —
        # a hallucinated id, or an attempt to describe a different structure.
        log.warning(
            "bounded selector named an id outside the offered set (offered %d); abstaining",
            len(allowed_ids),
        )
        return _abstain(
            "Model named a structure that was not among the approved candidates. "
            "Treated as an abstention and logged as malformed.",
            malformed=True,
        )

    return ModelSelection(
        candidate_id=chosen,
        rationale=rationale or "Model selected without a stated rationale.",
        abstained=False,
        malformed=False,
    )


class BoundedSelector:
    """Calls Claude with a fully-specified candidate list and validates the reply."""

    def __init__(self, settings: Settings | None = None, client: Any = None) -> None:
        self.settings = settings or default_settings
        self._client = client
        self.last_usage: dict[str, int] = {}

    @property
    def available(self) -> bool:
        return bool(self._client) or self.settings.has_model_credentials

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        import anthropic

        headers: dict[str, str] = {}
        # Identity-linked API keys require the workspace to be named explicitly.
        # Without it every request 400s, so it is surfaced as configuration
        # rather than discovered at the first live trade.
        if self.settings.anthropic_workspace_id:
            headers["anthropic-workspace-id"] = self.settings.anthropic_workspace_id

        self._client = anthropic.Anthropic(
            api_key=self.settings.anthropic_api_key,
            timeout=TIMEOUT_SECONDS,
            max_retries=1,
            default_headers=headers or None,
        )
        return self._client

    def select(
        self,
        vol: VolState,
        candidates: list[Candidate],
        risk: RiskAuthority,
    ) -> ModelSelection:
        """Choose one candidate, or abstain. Never raises."""
        # Rule one: no candidates means no call. Spending a token to be told
        # there is nothing to pick from would be silly, and it is one more
        # opportunity for the boundary to be tested for no benefit.
        if not candidates:
            return _abstain("No candidate survived the gate chain. Nothing to select.")

        if not self.available:
            return _abstain(
                "Bounded selector unavailable — no ANTHROPIC_API_KEY configured. "
                "Abstaining rather than trading without the selection step."
            )

        allowed = [c.id for c in candidates]
        message = build_user_message(vol, candidates, risk)

        try:
            client = self._get_client()
            response = client.messages.create(
                model=self.settings.anthropic_model,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
        except Exception as exc:  # noqa: BLE001 — any API failure is an abstention
            log.warning("bounded selector call failed: %s: %s", type(exc).__name__, exc)
            return _abstain(
                f"Bounded selector could not be reached ({type(exc).__name__}). "
                f"Abstaining — the desk does not trade when the selection step is down."
            )

        usage = getattr(response, "usage", None)
        self.last_usage = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
        }

        blocks = getattr(response, "content", []) or []
        raw = "".join(getattr(b, "text", "") for b in blocks)
        selection = validate_selection(raw, allowed)

        log.info(
            "bounded selector: %s (%d candidates offered, %d in / %d out tokens)",
            "ABSTAIN" if selection.abstained else selection.candidate_id,
            len(candidates),
            self.last_usage.get("input_tokens", 0),
            self.last_usage.get("output_tokens", 0),
        )
        return selection


def pick_candidate(candidates: list[Candidate], selection: ModelSelection) -> Candidate | None:
    """Resolve a validated selection back to a candidate object.

    Re-checks membership rather than trusting the selection: it is the last
    place a bad ID could get through, and the check costs nothing.
    """
    if selection.abstained or selection.candidate_id is None:
        return None
    for candidate in candidates:
        if candidate.id == selection.candidate_id:
            return candidate
    log.error("selection %r passed validation but matched no candidate", selection.candidate_id)
    return None
