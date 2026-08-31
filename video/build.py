#!/usr/bin/env python3
"""SKEW demo video pipeline — deterministic segments, re-render any one alone.

Phases implemented here: narration (1), captions (5), assembly (6), plus the
duration report (7's pre-encode gate). Browser capture (2) and motion pages (3)
are driven by capture.py against the same script.json.

Substitution rule: a file at vo/<id>.wav (user-recorded) always wins over
generation. Generated audio lives in vo/gen/, processed audio in vo/final/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

# ----------------------------------------------------------------- config
VOICE = "Samantha"  # best installed; swap for a Premium voice once downloaded
RATE = 170          # words per minute, 165-175 band
TARGET_URL = "https://skew.zevora.io"

ROOT = Path(__file__).parent
SCRIPT = ROOT / "script.json"
HEAD_PAD_S = 0.4
TAIL_PAD_S = 0.6
LUFS = -16


def sh(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"command failed: {' '.join(args)}\n{result.stderr[-800:]}")
    return result.stdout


def probe_duration(path: Path) -> float:
    out = sh("ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path))
    return float(out.strip())


def say_to_wav(text: str, dest: Path) -> None:
    aiff = dest.with_suffix(".aiff")
    # say writes AIFF natively; the LEF32 float format only applies to wav/caf
    # containers and errors on .aiff. ffmpeg resamples to 48k stereo anyway.
    sh("say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), text)
    sh("ffmpeg", "-y", "-v", "error", "-i", str(aiff),
       "-ar", "48000", "-ac", "2", str(dest))
    aiff.unlink()


def silence_wav(seconds: float, dest: Path) -> None:
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi",
       "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{seconds:.3f}", str(dest))


def concat_wavs(parts: list[Path], dest: Path) -> None:
    listfile = dest.with_suffix(".txt")
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
       "-i", str(listfile), "-c", "copy", str(dest))
    listfile.unlink()


def finalise(raw: Path, dest: Path) -> float:
    """Pad head/tail, loudness-normalise, return the measured duration."""
    sh("ffmpeg", "-y", "-v", "error", "-i", str(raw),
       "-af",
       f"adelay={int(HEAD_PAD_S * 1000)}|{int(HEAD_PAD_S * 1000)},"
       f"apad=pad_dur={TAIL_PAD_S},"
       f"loudnorm=I={LUFS}:TP=-1.5:LRA=11",
       "-ar", "48000", "-ac", "2", str(dest))
    return probe_duration(dest)


def build_vo() -> None:
    spec = json.loads(SCRIPT.read_text())
    gen = ROOT / "vo" / "gen"
    fin = ROOT / "vo" / "final"
    gen.mkdir(parents=True, exist_ok=True)
    fin.mkdir(parents=True, exist_ok=True)

    total = 0.0
    rows = []
    for seg in spec["segments"]:
        sid = seg["id"]
        override = ROOT / "vo" / f"{sid}.wav"
        raw = gen / f"{sid}.wav"

        if override.exists():
            source, src_label = override, "substituted"
        else:
            if "vo_parts" in seg:
                parts = []
                for i, part in enumerate(seg["vo_parts"]):
                    p = gen / f"{sid}_part{i}.wav"
                    if "silence_s" in part:
                        silence_wav(part["silence_s"], p)
                    else:
                        say_to_wav(part["text"], p)
                    parts.append(p)
                concat_wavs(parts, raw)
            else:
                say_to_wav(seg["vo"], raw)
            source, src_label = raw, "generated"

        final = fin / f"{sid}.wav"
        duration = finalise(source, final)
        duration = max(duration, float(seg.get("min_hold_s", 0)))
        seg["duration_s"] = round(duration, 3)
        total += seg["duration_s"]
        rows.append((sid, seg["title"], src_label, seg["duration_s"]))

    SCRIPT.write_text(json.dumps(spec, indent=2) + "\n")

    print(f"{'id':4} {'title':14} {'source':12} {'dur':>7}")
    for sid, title, src, dur in rows:
        print(f"{sid:4} {title:14} {src:12} {dur:7.2f}s")
    print(f"{'':32}total {total:6.2f}s  ({int(total // 60)}:{total % 60:04.1f})")
    if total > spec["meta"]["hard_ceiling_s"]:
        raise SystemExit(f"FAIL: {total:.1f}s exceeds the {spec['meta']['hard_ceiling_s']}s ceiling")


# ----------------------------------------------------------------- captions
def wrap_caption(text: str, width: int = 42) -> list[str]:
    """Cue lines of <=width chars, never breaking a word."""
    words = text.split()
    lines, line = [], ""
    for word in words:
        if len(line) + bool(line) + len(word) <= width:
            line = f"{line} {word}".strip()
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fmt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def build_srt() -> None:
    spec = json.loads(SCRIPT.read_text())
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    cues = []
    clock = 0.0
    for seg in spec["segments"]:
        duration = seg.get("duration_s")
        if duration is None:
            raise SystemExit("run `build.py vo` first — durations missing")
        text = seg.get("vo") or " ".join(
            p.get("text", "") for p in seg.get("vo_parts", [])
        )
        speech = duration - HEAD_PAD_S - TAIL_PAD_S
        lines = wrap_caption(text)
        # pair lines into 2-line cues; time proportional to character count
        pairs = [lines[i : i + 2] for i in range(0, len(lines), 2)]
        chars = [sum(len(l) for l in pair) for pair in pairs]
        total_chars = sum(chars) or 1
        t = clock + HEAD_PAD_S
        for pair, c in zip(pairs, chars):
            span = speech * c / total_chars
            cues.append((t, min(t + span, clock + duration), "\n".join(pair)))
            t += span
        clock += duration
    srt = "".join(
        f"{i}\n{fmt_ts(a)} --> {fmt_ts(b)}\n{txt}\n\n"
        for i, (a, b, txt) in enumerate(cues, 1)
    )
    (out / "skew.srt").write_text(srt)
    print(f"wrote out/skew.srt — {len(cues)} cues, ends {fmt_ts(clock)}")


# ----------------------------------------------------------------- segments
def build_segments() -> None:
    """Trim each capture to its exact scripted duration, freeze-pad if short,
    and mux the narration — every segment becomes a uniform 1080p30 mp4."""
    spec = json.loads(SCRIPT.read_text())
    for seg in spec["segments"]:
        sid = seg["id"]
        total = seg["total_s"]
        raw = ROOT / "frames" / f"{sid}.webm"
        vo = ROOT / "vo" / "final" / f"{sid}.wav"
        dest = ROOT / "frames" / f"{sid}.mp4"
        if not raw.exists():
            raise SystemExit(f"missing capture: {raw}")
        sh("ffmpeg", "-y", "-v", "error",
           "-i", str(raw), "-i", str(vo),
           "-filter_complex",
           f"[0:v]scale=1920:1080:flags=lanczos,fps=30,"
           f"tpad=stop_mode=clone:stop_duration=5,trim=duration={total},"
           f"setpts=PTS-STARTPTS[v];"
           f"[1:a]apad=whole_dur={total},atrim=duration={total},asetpts=PTS-STARTPTS[a]",
           "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-ar", "48000", "-ac", "2",
           str(dest))
        print(f"{sid}: {dest.name} @ {total:.2f}s")


# ------------------------------------------------------------- caption burn
def cue_list() -> list[tuple[float, float, str]]:
    """The same cue timing build_srt writes, as data."""
    spec = json.loads(SCRIPT.read_text())
    cues, clock = [], 0.0
    for seg in spec["segments"]:
        duration = seg["total_s"]
        text = seg.get("vo") or " ".join(p.get("text", "") for p in seg.get("vo_parts", []))
        speech = seg["duration_s"] - HEAD_PAD_S - TAIL_PAD_S
        lines = wrap_caption(text)
        pairs = [lines[i : i + 2] for i in range(0, len(lines), 2)]
        chars = [sum(len(l) for l in pair) for pair in pairs]
        total_chars = sum(chars) or 1
        t = clock + HEAD_PAD_S
        for pair, c in zip(pairs, chars):
            span = speech * c / total_chars
            cues.append((t, min(t + span, clock + duration), "\n".join(pair)))
            t += span
        clock += duration
    return cues


def burn_captions(master: Path, dest: Path) -> None:
    """This ffmpeg build ships without libass or drawtext, so cues are rendered
    as transparent PNG strips in the site's own type and overlaid with time
    windows — sharper than libass would have been anyway."""
    from playwright.sync_api import sync_playwright

    cues = cue_list()
    strip_dir = ROOT / "out" / "cues"
    strip_dir.mkdir(exist_ok=True)
    html = """<!doctype html><meta charset='utf-8'><style>
      body{margin:0;width:1920px;height:150px;background:transparent;display:flex;
           align-items:flex-end;justify-content:center;font-family:-apple-system,'Manrope',sans-serif}
      .cap{background:rgba(16,16,19,.82);color:#f4f4f6;font-size:34px;line-height:1.35;
           padding:12px 28px;border-radius:12px;text-align:center;white-space:pre-line;
           margin-bottom:0}</style><body><div class='cap' id='c'></div></body>"""
    page_file = strip_dir / "cap.html"
    page_file.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1920, "height": 150}, device_scale_factor=1
        )
        page.goto(f"file://{page_file}")
        for i, (_, _, text) in enumerate(cues):
            page.evaluate("t => document.getElementById('c').textContent = t", text)
            page.screenshot(path=str(strip_dir / f"c{i:02}.png"), omit_background=True)
        browser.close()

    inputs, chain = ["-i", str(master)], []
    for i, _ in enumerate(cues):
        inputs += ["-i", str(strip_dir / f"c{i:02}.png")]
    prev = "0:v"
    for i, (a, b, _) in enumerate(cues):
        label = f"v{i}"
        chain.append(
            f"[{prev}][{i + 1}:v]overlay=x=(W-w)/2:y=H-h-90:"
            f"enable='between(t,{a:.3f},{b:.3f})'[{label}]"
        )
        prev = label
    sh("ffmpeg", "-y", "-v", "error", *inputs,
       "-filter_complex", ";".join(chain), "-map", f"[{prev}]", "-map", "0:a",
       "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
       "-c:a", "copy", "-movflags", "+faststart", str(dest))
    print(f"burned-in captions master: {dest.name} ({len(cues)} cues)")


# ----------------------------------------------------------------- assembly
def assemble() -> None:
    """Concat per-segment renders (frames/<id>.mp4, already muxed with VO) via
    the concat demuxer, then encode masters. Run after capture."""
    spec = json.loads(SCRIPT.read_text())
    out = ROOT / "out"
    listfile = out / "concat.txt"
    segs = [ROOT / "frames" / f"{seg['id']}.mp4" for seg in spec["segments"]]
    missing = [p.name for p in segs if not p.exists()]
    if missing:
        raise SystemExit(f"missing segment renders: {missing}")
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    master = out / "skew-demo.mp4"
    # Segments are already uniform h264/aac — concat demuxer with stream copy,
    # no re-encode drift.
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
       "-c", "copy", "-movflags", "+faststart", str(master))
    duration = probe_duration(master)
    print(f"clean master: {master} — {duration:.1f}s")
    if duration > spec["meta"]["hard_ceiling_s"]:
        raise SystemExit(f"FAIL: {duration:.1f}s exceeds the ceiling")
    if (out / "skew.srt").exists():
        burn_captions(master, out / "skew-demo-captions.mp4")
    sh("ffmpeg", "-y", "-v", "error", "-i", str(master),
       "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", "-c:a", "libopus",
       str(out / "skew-demo.webm"))
    print("webm fallback written")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "vo"
    {"vo": build_vo, "srt": build_srt, "segments": build_segments, "assemble": assemble}[phase]()
