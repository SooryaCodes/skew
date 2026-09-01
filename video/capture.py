#!/usr/bin/env python3
"""Segment capture v2 — cursor-driven, anchored, asserted.

Every UI segment shows intent: a visible accent-ring cursor travels on eased
paths before every click, scroll is anchored to real elements and asserted
in-viewport, and any figure the narration speaks is read off the captured DOM
(a21, a31b) or verified present in the frame (structural constants). Failures
are collected into out/numeric-verification.json for review.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def sh(*args: str) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args[:2])}")
    return proc.stdout

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
SPEC_PATH = ROOT / "script.json"
SPEC = json.loads(SPEC_PATH.read_text())
TARGET = SPEC["meta"]["target_url"]
API = "https://api-production-4d3d.up.railway.app"
FRAMES = ROOT / "frames"
FRAMES.mkdir(exist_ok=True)
VERIFY: list[dict] = []

OVERLAY_CSS = """
#vd-cursor{position:fixed;z-index:999999;width:34px;height:34px;margin:-17px 0 0 -17px;
border:2.5px solid #7c7cf2;border-radius:50%;pointer-events:none;left:-100px;top:-100px;
box-shadow:0 0 14px rgba(124,124,242,.45);transition:none}
#vd-cursor.pulse{animation:vdp .35s ease}
@keyframes vdp{40%{transform:scale(.72)}100%{transform:scale(1)}}
.vd-ring{position:fixed;z-index:999998;pointer-events:none;border:2.5px solid #7c7cf2;
border-radius:12px;animation:vdf .4s ease both}
.vd-under{position:fixed;z-index:999998;pointer-events:none;height:3px;background:#7c7cf2;
border-radius:2px;animation:vdf .4s ease both}
.vd-chip{position:fixed;z-index:999999;background:rgba(16,16,19,.94);border:1px solid #232329;
border-radius:10px;padding:10px 18px;font:600 22px -apple-system,"Manrope",sans-serif;
color:#f4f4f6;animation:vdf .4s ease both}
.vd-lower{position:fixed;left:0;bottom:210px;z-index:999999;background:rgba(16,16,19,.92);
border:1px solid #232329;border-left:none;border-radius:0 12px 12px 0;padding:16px 28px;
font:500 24px "Geist Mono",ui-monospace,Menlo,monospace;color:#f4f4f6;
transform:translateX(-105%);animation:vdin .3s cubic-bezier(.2,.8,.2,1) .3s forwards}
@keyframes vdin{to{transform:none}}
@keyframes vdf{from{opacity:0}to{opacity:1}}
"""


def words_for(value: float) -> str:
    """Small spoken-number converter for the figures we narrate."""
    ones = ["zero","one","two","three","four","five","six","seven","eight","nine","ten",
            "eleven","twelve","thirteen","fourteen","fifteen","sixteen","seventeen",
            "eighteen","nineteen"]
    tens = ["","","twenty","thirty","forty","fifty","sixty","seventy","eighty","ninety"]

    def integer_words(n: int) -> str:
        if n < 20:
            return ones[n]
        if n < 100:
            return tens[n // 10] + ("" if n % 10 == 0 else " " + ones[n % 10])
        if n < 1000:
            head = ones[n // 100] + " hundred"
            return head + ("" if n % 100 == 0 else " and " + integer_words(n % 100))
        if n < 1_000_000:
            head = integer_words(n // 1000) + " thousand"
            return head + ("" if n % 1000 == 0 else " " + integer_words(n % 1000))
        return str(n)

    whole = int(round(value)) if abs(value - round(value)) < 0.05 else None
    if whole is not None:
        return integer_words(whole)
    return integer_words(int(value)) + " point " + ones[int(round(value * 10)) % 10]


def inject(page):
    page.add_style_tag(content=OVERLAY_CSS)
    page.evaluate("""() => { if (!document.getElementById('vd-cursor')) {
        const c = document.createElement('div'); c.id = 'vd-cursor';
        document.body.appendChild(c); } }""")


def cursor_to(page, x: float, y: float, ms: int = 500):
    page.evaluate(
        """([x, y, ms]) => new Promise(done => {
            const c = document.getElementById('vd-cursor');
            const sx = parseFloat(c.style.left || 960), sy = parseFloat(c.style.top || 540);
            const t0 = performance.now();
            const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2;
            (function step(now) {
                const t = Math.min(1, (now - t0) / ms);
                c.style.left = (sx + (x - sx) * ease(t)) + 'px';
                c.style.top  = (sy + (y - sy) * ease(t)) + 'px';
                t < 1 ? requestAnimationFrame(step) : done();
            })(t0);
        })""",
        [x, y, ms],
    )


def rect_of(page, label: str):
    return page.evaluate(
        """(label) => {
          const pool = [...document.querySelectorAll('p,span,h2,h3,div,button,a,th,td,dt,dd,li')]
            .filter(e => e.childElementCount === 0);
          const want = label.toUpperCase();
          const el = pool.find(e => e.textContent.trim().toUpperCase() === want)
                  || pool.find(e => e.textContent.trim().toUpperCase().startsWith(want));
          if (!el) return null;
          const r = (el.parentElement || el).getBoundingClientRect();
          return {x: r.x, y: r.y, w: r.width, h: r.height};
        }""",
        label,
    )


def cursor_click(page, x: float, y: float):
    cursor_to(page, x, y, 550)
    page.wait_for_timeout(200)
    page.evaluate("document.getElementById('vd-cursor').classList.add('pulse')")
    page.mouse.click(x, y)
    page.wait_for_timeout(380)
    page.evaluate("document.getElementById('vd-cursor').classList.remove('pulse')")


def ring(page, label: str, underline: bool = False):
    box = rect_of(page, label)
    if not box:
        VERIFY.append({"kind": "highlight-miss", "label": label})
        return
    page.evaluate(
        """([b, u]) => {
          const el = document.createElement('div');
          el.className = u ? 'vd-under' : 'vd-ring';
          if (u) Object.assign(el.style, {left:b.x+'px', top:(b.y+b.h+4)+'px', width:b.w+'px'});
          else Object.assign(el.style, {left:(b.x-10)+'px', top:(b.y-10)+'px',
                                        width:(b.w+20)+'px', height:(b.h+20)+'px'});
          document.body.appendChild(el);
        }""",
        [box, underline],
    )


def chip(page, text: str, x: int, y: int):
    page.evaluate(
        """([t, x, y]) => { const el = document.createElement('div');
            el.className = 'vd-chip'; el.textContent = t;
            el.style.left = x + 'px'; el.style.top = y + 'px';
            document.body.appendChild(el); }""",
        [text, x, y],
    )


def lower_third(page, text: str):
    page.evaluate(
        """(t) => { const el = document.createElement('div');
            el.className = 'vd-lower'; el.textContent = t;
            document.body.appendChild(el); }""",
        text,
    )


def anchored_scroll(page, find_js: str, offset: int = 90, ms: int = 1400):
    """Tween the element's own scroll container to bring it to `offset` from
    the top, then ASSERT it is fully inside the viewport. No overshoot."""
    ok = page.evaluate(
        """async ([findJs, offset, ms]) => {
          const el = eval(findJs);
          if (!el) return 'element not found';
          let sc = el.parentElement;
          while (sc && sc !== document.body) {
            const cs = getComputedStyle(sc);
            if ((cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                sc.scrollHeight > sc.clientHeight) break;
            sc = sc.parentElement;
          }
          const container = (sc && sc !== document.body) ? sc : document.scrollingElement;
          const base = container === document.scrollingElement ? 0
                     : container.getBoundingClientRect().top;
          const target = Math.max(0, Math.min(
            container.scrollTop + el.getBoundingClientRect().top - base - offset,
            container.scrollHeight - container.clientHeight));
          const start = container.scrollTop, delta = target - start;
          const t0 = performance.now();
          const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2;
          await new Promise(done => (function step(now) {
              const t = Math.min(1, (now - t0) / ms);
              container.scrollTop = start + delta * ease(t);
              t < 1 ? requestAnimationFrame(step) : done();
          })(t0));
          const r = el.getBoundingClientRect();
          if (r.top < -4 || r.top > innerHeight - 40) return `overshoot: top=${r.top}`;
          return 'ok';
        }""",
        [find_js, offset, ms],
    )
    if ok != "ok":
        raise RuntimeError(f"anchored_scroll failed: {ok}")


def by_text(label: str) -> str:
    return (
        "[...document.querySelectorAll('p,span,h2,h3,div')].find(e =>"
        f" e.childElementCount === 0 && e.textContent.trim().toUpperCase() ==="
        f" {json.dumps(label.upper())})"
    )


def read_metric(page, label: str) -> float:
    value = page.evaluate(
        """(label) => {
          const el = [...document.querySelectorAll('p,span')]
            .find(e => e.childElementCount === 0 &&
                       e.textContent.trim().toUpperCase() === label);
          if (!el) return null;
          const holder = el.parentElement;
          const num = holder.querySelector('.hero-num, [class*="font-display"]');
          return num ? num.textContent.trim() : null;
        }""",
        label.upper(),
    )
    if value is None:
        raise RuntimeError(f"metric {label} not found on frame")
    return float(value.replace("−", "-").replace("+", ""))


def verify_numbers(page, sid: str, spoken: list[str]):
    text = page.evaluate("document.body.innerText")
    for token in spoken:
        found = token in text
        VERIFY.append({"segment": sid, "token": token, "on_frame": found})
        if not found:
            print(f"  VERIFY-FLAG {sid}: {token!r} not visible on frame")


def settle(page, ms=2500):
    page.wait_for_timeout(ms)


def scene(p, seg, ctx_extra=None):
    sid = seg["id"]
    hold = seg.get("total_s", seg.get("duration_s", 12)) + 1.2
    t0 = time.time()
    ready_at = {"t": 0.0}

    def mark_ready():
        # Everything recorded before this instant is page-load noise; the mux
        # trims it so second zero of the segment is the settled scene.
        ready_at["t"] = round(time.time() - t0, 3)
    browser = p.chromium.launch()
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080}, device_scale_factor=2,
        color_scheme="dark", record_video_dir=str(FRAMES / "raw"),
        record_video_size={"width": 1920, "height": 1080},
        reduced_motion="no-preference",
    )
    page = ctx.new_page()
    result = {}
    kind = seg.get("kind")

    if kind == "motion":
        page.goto(f"file://{ROOT / seg['page']}")
        page.wait_for_timeout(250)
        mark_ready()
        page.wait_for_timeout(int(hold * 1000))

    elif sid == "a21":
        page.goto(f"{TARGET}/desk?shot=1&theme=dark", wait_until="networkidle")
        page.wait_for_selector("text=VRP", timeout=30000)
        settle(page)
        inject(page)
        mark_ready()
        row = page.evaluate(
            """() => { const rows=[...document.querySelectorAll('nav[aria-label="Universe"] button')];
              const best = rows.map(b=>({b, v:parseFloat((b.textContent.match(/[+\\u2212-]\\d+\\.\\d/)||['0'])[0].replace('\\u2212','-'))}))
                .sort((x,y)=>y.v-x.v)[0];
              if (!best || best.v <= 0) return null;
              const r = best.b.getBoundingClientRect();
              return {x: r.x + r.width/2, y: r.y + r.height/2}; }"""
        )
        if row:
            cursor_click(page, row["x"], row["y"])
            settle(page, 2000)
        iv = read_metric(page, "IV ATM")
        rv = read_metric(page, "RV 20D")
        vrp = read_metric(page, "VRP")
        result = {"iv": iv, "rv": rv, "vrp": vrp}
        ring(page, "IV ATM"); page.wait_for_timeout(2600)
        ring(page, "RV 20D"); page.wait_for_timeout(2600)
        ring(page, "VRP"); page.wait_for_timeout(2200)
        cursor_to(page, 1200, 760, 900)
        page.wait_for_timeout(int(hold * 1000))
        end_iv = read_metric(page, "IV ATM")
        if abs(end_iv - iv) > 0.05:
            raise RuntimeError(
                f"selection did not hold: IV read {iv} at click, {end_iv} at end"
            )
        verify_numbers(page, sid, [f"{iv:.1f}", f"{rv:.1f}", f"{abs(vrp):.1f}"])

    elif sid == "a22":
        page.goto(f"{TARGET}/desk?shot=1&theme=dark", wait_until="networkidle")
        page.wait_for_selector("text=CANDIDATES", timeout=30000)
        settle(page)
        inject(page)
        mark_ready()
        tab = page.evaluate(
            """() => { const t = document.querySelector('[role=tab]');
                 if (!t) return null; const r = t.getBoundingClientRect();
                 return {x: r.x + r.width/2, y: r.y + r.height/2}; }"""
        )
        if tab:
            cursor_click(page, tab["x"], tab["y"])
            page.wait_for_timeout(800)
        anchored_scroll(page, by_text("candidates"), 60)
        page.wait_for_timeout(1500)
        ring(page, "MAX LOSS")
        ring(page, "DEBIT")
        cursor_to(page, 1100, 500, 800)
        page.wait_for_timeout(int(hold * 1000))
        verify_numbers(page, sid, [])

    elif sid == "a23":
        page.goto(f"{TARGET}/desk?shot=1&theme=dark", wait_until="networkidle")
        page.wait_for_selector("text=CANDIDATES", timeout=30000)
        settle(page)
        inject(page)
        mark_ready()
        anchored_scroll(page, by_text("candidates"), 40)
        page.wait_for_timeout(1200)
        for label in ("liquidity", "earnings", "term", "stress", "budget"):
            box = rect_of(page, label)
            if box:
                cursor_to(page, box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, 450)
                page.wait_for_timeout(900)
        page.wait_for_timeout(int(hold * 1000))

    elif sid == "a31":
        page.goto(f"{TARGET}/?theme=dark&capture=1", wait_until="networkidle")
        settle(page, 3000)
        inject(page)
        mark_ready()
        anchored_scroll(page, "[...document.querySelectorAll('section')].find(s=>s.getAttribute('aria-label')==='The refusal')", 0, 2200)
        page.wait_for_timeout(600)
        page.evaluate(
            """async () => { const start = scrollY; const t0 = performance.now();
              const ease = t => t < .5 ? 2*t*t : 1 - Math.pow(-2*t+2, 2)/2;
              await new Promise(done => (function step(now) {
                const t = Math.min(1, (now - t0) / 4200);
                scrollTo(0, start + 780 * ease(t));
                t < 1 ? requestAnimationFrame(step) : done(); })(t0)); }"""
        )
        chip(page, "recorded 30 August · development desk", 1210, 150)
        # Timed to the narration parts: hold the grid through the payload and
        # the beat, then travel to the gate-chain section while the aside plays
        # — "the gate is the floor" over the literal gates. Part durations are
        # probed from the rendered audio so picture and words stay locked.
        def part_dur(name):
            f = ROOT / "vo" / "gen" / name
            return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(f)).strip()) if f.exists() else 0.0

        payload = part_dur("a31_part0.wav") + 1.5 + part_dur("a31_part2.wav")
        page.wait_for_timeout(int((payload + 0.6) * 1000))
        anchored_scroll(
            page,
            "[...document.querySelectorAll('section')].find(s=>s.getAttribute('aria-label')==='Architecture')",
            60,
            2400,
        )
        remaining = max(2.0, hold - payload - 3.2)
        page.wait_for_timeout(int(remaining * 1000))
        verify_numbers(page, sid, ["84"])

    elif sid == "a31b":
        page.goto(f"{TARGET}/desk?shot=1&theme=dark", wait_until="networkidle")
        page.wait_for_selector("text=Audit log", timeout=30000)
        settle(page)
        inject(page)
        mark_ready()
        with urllib.request.urlopen(f"{API}/api/audit/counts", timeout=20) as r:
            counts = json.load(r)
        looked, acted = counts["TOTAL"], counts["EXECUTED"]
        result = {"looked": looked, "acted": acted}
        for chip_label in ("Filled", "All"):
            # Scoped to the filter group — an unscoped text match once hit the
            # "Filled" BADGE on an audit entry and clicked through to its trace.
            box = page.evaluate(
                """(label) => {
                  const group = document.querySelector('[role="group"][aria-label="Filter decisions"]');
                  if (!group) return null;
                  const btn = [...group.querySelectorAll('button')]
                    .find(b => b.textContent.trim().startsWith(label));
                  if (!btn) return null;
                  const r = btn.getBoundingClientRect();
                  return {x: r.x, y: r.y, w: r.width, h: r.height};
                }""",
                chip_label,
            )
            if box:
                cursor_click(page, box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
                page.wait_for_timeout(1600)
        ring(page, "Audit log")
        page.wait_for_timeout(int(hold * 1000))
        verify_numbers(page, sid, [str(acted)])

    elif sid == "a32":
        page.goto(f"{TARGET}/positions?theme=dark", wait_until="networkidle")
        settle(page)
        inject(page)
        mark_ready()
        lower_third(page, "one atomic multi-leg order · four legs together")
        ring(page, "LEGS")
        cursor_to(page, 700, 450, 900)
        page.wait_for_timeout(int(hold * 1000))
        verify_numbers(page, sid, ["100,000"])

    elif sid == "a33":
        page.goto(f"{TARGET}/desk?shot=1&theme=dark", wait_until="networkidle")
        page.wait_for_selector("text=RISK AUTHORITY", timeout=30000)
        settle(page)
        inject(page)
        mark_ready()
        ring(page, "RISK AUTHORITY")
        page.wait_for_timeout(2500)
        ring(page, "EQUITY", underline=True)
        box = rect_of(page, "PER TRADE")
        if box:
            cursor_to(page, box["x"] + box["w"] / 2, box["y"] + box["h"] / 2, 700)
        page.wait_for_timeout(int(hold * 1000))
        verify_numbers(page, sid, ["0.5%", "$100,000"])

    elif sid == "a34":
        page.goto(f"{TARGET}/mcp?theme=dark", wait_until="networkidle")
        settle(page, 2000)
        inject(page)
        mark_ready()
        lower_third(page, "skew.zevora.io/mcp")
        anchored_scroll(page, by_text("read tools — always on"), 120, 1600)
        page.wait_for_timeout(3500)
        anchored_scroll(page, by_text("write tools — off unless enabled, confirm-required"), 140, 1600)
        ring(page, "WRITE TOOLS — OFF UNLESS ENABLED, CONFIRM-REQUIRED", underline=True)
        page.wait_for_timeout(int(hold * 1000))
        verify_numbers(page, sid, [])

    elif sid == "a35":
        with urllib.request.urlopen(f"{API}/api/audit?limit=1", timeout=20) as r:
            trace_id = json.load(r)[0]["id"]
        page.goto(f"{TARGET}/trace/{trace_id}?theme=dark", wait_until="networkidle")
        settle(page)
        inject(page)
        mark_ready()
        anchored_scroll(page, by_text("gate"), 200, 1800)
        page.wait_for_timeout(int(hold * 1000))

    video = page.video
    page.close(); ctx.close()
    src = Path(video.path())
    dest = FRAMES / f"{sid}.webm"
    dest.unlink(missing_ok=True)
    src.rename(dest)
    browser.close()
    (FRAMES / f"{sid}.json").write_text(json.dumps({"head_trim": ready_at["t"]}))
    print(f"{sid}: captured (head trim {ready_at['t']:.1f}s)")
    return result


def materialise_deferred(sid: str, values: dict):
    """Write the capture-derived narration into script.json."""
    spec = json.loads(SPEC_PATH.read_text())
    seg = next(s for s in spec["segments"] if s["id"] == sid)
    if sid == "a21":
        seg["vo"] = seg["vo_template"].format(
            iv_words=words_for(values["iv"]),
            rv_words=words_for(values["rv"]),
            vrp_words=words_for(abs(values["vrp"])),
        )
    elif sid == "a31b":
        seg["vo"] = seg["vo_template"].format(
            looked_words=words_for(values["looked"]),
            acted_words=words_for(values["acted"]),
        )
    SPEC_PATH.write_text(json.dumps(spec, indent=2) + "\n")
    print(f"{sid} narration materialised: {seg['vo'][:110]}…")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    # Last check before capture: film a REAL competition refusal if one landed.
    with urllib.request.urlopen(f"{API}/api/audit/counts", timeout=20) as r:
        counts = json.load(r)
    print(f"pre-capture refusal check: REFUSED={counts['REFUSED']}"
          f" -> {'REAL refusal available — see report' if counts['REFUSED'] else 'using labelled dev exhibit'}")

    failures = []
    with sync_playwright() as p:
        for seg in SPEC["segments"]:
            if only and seg["id"] != only:
                continue
            try:
                values = scene(p, seg)
                if seg.get("deferred") and values:
                    materialise_deferred(seg["id"], values)
            except Exception as exc:
                failures.append(seg["id"])
                print(f"{seg['id']}: FAILED — {str(exc).splitlines()[0][:140]}")
    (ROOT / "out").mkdir(exist_ok=True)
    (ROOT / "out" / "numeric-verification.json").write_text(json.dumps(VERIFY, indent=2))
    flagged = [v for v in VERIFY if v.get("on_frame") is False or v.get("kind")]
    print(f"numeric verification: {len(VERIFY)} checks, {len(flagged)} flagged")
    if failures:
        raise SystemExit(f"re-run needed: {failures}")
