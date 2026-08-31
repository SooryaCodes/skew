#!/usr/bin/env python3
"""Regression check: /desk scroll containment, both layout regimes.

At lg (>=1024px) the desk is a fixed-height shell: the page must not scroll,
the footer must sit inside the viewport, and the audit list must scroll
internally. Below lg the desk is normal flow: the page scrolls its CONTENT,
with no orphaned empty region past the footer. This regressed once by height
classes leaking out of the lg scope — this script keeps it dead.

Usage: python3 scripts/check_desk_containment.py [base_url]
"""

import sys

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name} — {detail}")
    if not ok:
        FAILURES.append(name)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, regime in ((1440, "lg"), (1000, "stacked")):
        page = browser.new_page(viewport={"width": width, "height": 900})
        page.goto(f"{BASE}/desk", wait_until="networkidle")
        page.wait_for_timeout(1500)
        m = page.evaluate(
            """() => {
              const doc = document.documentElement;
              const footer = [...document.querySelectorAll('footer')]
                .find(f => f.textContent.includes('paper trading only'))
                .getBoundingClientRect();
              const ul = document.querySelector('section[aria-label="Decision stream"] ul');
              return {
                scrollH: doc.scrollHeight,
                innerH: innerHeight,
                footerBottomDoc: footer.bottom + scrollY,
                ulScrollable: ul ? (ul.scrollHeight > ul.clientHeight &&
                  getComputedStyle(ul).overflowY === 'auto') : null,
              };
            }"""
        )
        if regime == "lg":
            check("lg: page does not scroll", m["scrollH"] <= m["innerH"] + 2,
                  f"scrollH {m['scrollH']} vs viewport {m['innerH']}")
            check("lg: footer inside viewport", m["footerBottomDoc"] <= m["innerH"] + 2,
                  f"footer bottom {m['footerBottomDoc']:.0f}")
            check("lg: audit list scrolls internally", bool(m["ulScrollable"]),
                  f"ulScrollable={m['ulScrollable']}")
        else:
            empty = m["scrollH"] - m["footerBottomDoc"]
            check("stacked: no void past the footer", empty <= 40,
                  f"{empty:.0f}px below footer (document {m['scrollH']})")
        page.close()
    browser.close()

if FAILURES:
    raise SystemExit(f"containment regressed: {FAILURES}")
print("desk containment holds in both regimes")
