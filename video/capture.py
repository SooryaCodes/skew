#!/usr/bin/env python3
"""Per-segment browser capture against the live site. Playwright, deterministic.

Each segment records to frames/<id>.webm at 1920x1080; build.py then trims,
retimes and muxes narration. Overlays (lower third, callouts) are injected
into the captured page as DOM so compositing is exact with no alpha pass.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
SPEC = json.loads((ROOT / "script.json").read_text())
TARGET = SPEC["meta"]["target_url"]
FRAMES = ROOT / "frames"
FRAMES.mkdir(exist_ok=True)

LOWER_THIRD_CSS = """
.vd-lower{position:fixed;left:0;bottom:96px;z-index:99999;background:rgba(16,16,19,.92);
border:1px solid #232329;border-left:none;border-radius:0 12px 12px 0;padding:18px 30px;
font-family:"Geist Mono",ui-monospace,Menlo,monospace;font-size:26px;color:#f4f4f6;
transform:translateX(-105%);animation:vdin .3s cubic-bezier(.2,.8,.2,1) .4s forwards}
@keyframes vdin{to{transform:none}}
.vd-callout{position:fixed;z-index:99999;pointer-events:none;border:2.5px solid #7c7cf2;
border-radius:14px;box-shadow:0 0 0 6000px rgba(9,9,11,.28);animation:vdfade .5s ease .3s both}
@keyframes vdfade{from{opacity:0}to{opacity:1}}
.vd-big{position:fixed;z-index:99999;font-family:-apple-system,"Manrope",sans-serif;
font-weight:800;font-size:120px;letter-spacing:-0.03em;color:#f4f4f6;
background:rgba(16,16,19,.9);border:1px solid #232329;border-radius:18px;padding:12px 42px;
animation:vdfade .5s ease .6s both}
.vd-line{position:fixed;z-index:99998;height:2px;background:#7c7cf2;transform-origin:left;
animation:vdfade .4s ease .5s both}
"""


def smooth_scroll(page, y: int, ms: int = 1200):
    page.evaluate(
        """([target, ms]) => new Promise(done => {
             const start = scrollY, delta = target - start, t0 = performance.now();
             const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2;
             (function step(now){
                const t = Math.min(1, (now - t0)/ms);
                scrollTo(0, start + delta * ease(t));
                t < 1 ? requestAnimationFrame(step) : done();
             })(t0);
           })""",
        [y, ms],
    )


def inject(page, css=True):
    if css:
        page.add_style_tag(content=LOWER_THIRD_CSS)


def callout_text(page, label: str, big_text: str | None = None):
    """Ring the PARENT of the element whose trimmed text equals ``label``.
    Resilient: computed in page JS, and a miss is a no-op, never a crash."""
    box = page.evaluate(
        """(label) => {
          const el = [...document.querySelectorAll('p,span,h2,h3,div')]
            .find(e => e.childElementCount === 0 && e.textContent.trim().toUpperCase() === label.toUpperCase());
          if (!el) return null;
          const r = (el.parentElement || el).getBoundingClientRect();
          return {x:r.x, y:r.y, width:r.width, height:r.height};
        }""",
        label,
    )
    if not box:
        print(f"  (callout '{label}' not found — skipped)")
        return
    pad = 14
    page.evaluate(
        """([b, pad, big]) => {
          const ring = document.createElement('div');
          ring.className = 'vd-callout';
          Object.assign(ring.style, {left:(b.x-pad)+'px', top:(b.y-pad)+'px',
            width:(b.width+2*pad)+'px', height:(b.height+2*pad)+'px'});
          document.body.appendChild(ring);
          if (big) {
            const line = document.createElement('div');
            line.className = 'vd-line';
            Object.assign(line.style, {left:(b.x+b.width+pad)+'px', top:(b.y+b.height/2)+'px',
              width:'120px'});
            document.body.appendChild(line);
            const el = document.createElement('div');
            el.className = 'vd-big'; el.textContent = big;
            Object.assign(el.style, {left:(b.x+b.width+pad+140)+'px',
              top:(b.y+b.height/2-90)+'px'});
            document.body.appendChild(el);
          }
        }""",
        [box, pad, big_text],
    )


def lower_third(page, text: str):
    page.evaluate(
        """(t) => { const el = document.createElement('div');
             el.className = 'vd-lower'; el.textContent = t;
             document.body.appendChild(el); }""",
        text,
    )


def capture_segment(p, seg, trace_id: str | None):
    sid = seg["id"]
    hold = seg["total_s"] + 1.0  # margin; build trims to exact duration
    browser = p.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        device_scale_factor=2,
        record_video_dir=str(FRAMES / "raw"),
        record_video_size={"width": 1920, "height": 1080},
        reduced_motion="no-preference",
    )
    page = ctx.new_page()

    def read_value(sel):
        try:
            return page.locator(sel).first.inner_text(timeout=3000)
        except Exception:
            return None

    if sid == "s1":
        page.goto(f"file://{ROOT / 'motion' / 'title.html'}")
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s2":
        page.goto(f"{TARGET}/desk?shot=1", wait_until="networkidle")
        page.wait_for_selector("text=VRP", timeout=30000)
        page.wait_for_timeout(2500)
        inject(page)
        vrp = page.evaluate(
            """() => { const el=[...document.querySelectorAll('p,span')]
                 .find(e=>e.childElementCount===0 && e.textContent.trim().toUpperCase()==='VRP');
                 const sib = el && el.parentElement.querySelector('.hero-num, [class*=font-display]');
                 return sib ? sib.textContent.trim() : null; }"""
        )
        callout_text(page, "VRP", vrp)
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s3":
        page.goto(f"{TARGET}/desk?shot=1", wait_until="networkidle")
        page.wait_for_selector("text=CANDIDATES", timeout=30000)
        page.wait_for_timeout(2000)
        smooth_scroll(page, 500, 1400)
        page.wait_for_timeout(1200)
        inject(page)
        callout_text(page, "MAX LOSS")
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s4":
        page.goto(TARGET, wait_until="networkidle")
        page.wait_for_timeout(2500)
        target_y = page.evaluate(
            "() => { const el=[...document.querySelectorAll('section')]"
            ".find(s=>s.getAttribute('aria-label')==='The refusal');"
            "return el ? el.getBoundingClientRect().top + scrollY - 40 : 4000; }"
        )
        smooth_scroll(page, int(target_y), 2600)
        page.wait_for_timeout(800)
        smooth_scroll(page, int(target_y) + 700, 3500)  # scrub the pin
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s5":
        page.goto(f"{TARGET}/positions", wait_until="networkidle")
        page.wait_for_timeout(2500)
        inject(page)
        lower_third(page, "one atomic multi-leg order · both legs together")
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s6":
        page.goto(f"{TARGET}/desk?shot=1", wait_until="networkidle")
        page.wait_for_selector("text=RISK AUTHORITY", timeout=30000)
        page.wait_for_timeout(2000)
        inject(page)
        callout_text(page, "RISK AUTHORITY")
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s7":
        page.goto(f"{TARGET}/mcp", wait_until="networkidle")
        page.wait_for_timeout(1500)
        inject(page)
        lower_third(page, "skew.zevora.io/mcp")
        smooth_scroll(page, 600, 2600)
        page.wait_for_timeout(2500)
        smooth_scroll(page, 1400, 3200)
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s8":
        page.goto(f"{TARGET}/trace/{trace_id}", wait_until="networkidle")
        page.wait_for_timeout(2500)
        smooth_scroll(page, 700, 3000)
        page.wait_for_timeout(int(hold * 1000))
    elif sid == "s9":
        page.goto(f"file://{ROOT / 'motion' / 'end.html'}")
        page.wait_for_timeout(int(hold * 1000))

    video = page.video
    page.close()
    ctx.close()
    path = Path(video.path())
    dest = FRAMES / f"{sid}.webm"
    dest.unlink(missing_ok=True)
    path.rename(dest)
    browser.close()
    print(f"{sid}: captured {dest.name}")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    import urllib.request

    with urllib.request.urlopen(
        "https://api-production-4d3d.up.railway.app/api/audit?limit=1", timeout=20
    ) as r:
        trace_id = json.load(r)[0]["id"]
    failures = []
    with sync_playwright() as p:
        for seg in SPEC["segments"]:
            if only and seg["id"] != only:
                continue
            try:
                capture_segment(p, seg, trace_id)
            except Exception as exc:  # keep going; re-run the one that failed
                failures.append(seg["id"])
                print(f"{seg['id']}: FAILED — {str(exc).splitlines()[0][:140]}")
    if failures:
        raise SystemExit(f"re-run needed for: {failures}")
