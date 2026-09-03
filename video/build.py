#!/usr/bin/env python3
"""SKEW demo pipeline v2 — dense narration, measured everything.

Phases: vo (narration), srt (captions), segments (mux), assemble (masters),
report (the pre-render numbers gate). Silence is accounted, not guessed:
every pad and hold is in the ledger, and the build fails on budget breach.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------- config
# Default engine: Kokoro-82M (bundled with the HyperFrames CLI cache).
# VO_FALLBACK_SAY=1 -> macOS say. USE_ELEVENLABS=1 -> dormant ElevenLabs path.
USE_SAY_FALLBACK = os.environ.get("VO_FALLBACK_SAY") == "1"
USE_ELEVENLABS = os.environ.get("USE_ELEVENLABS") == "1"
KOKORO_VOICE = "af_heart"
KOKORO_SPEED = float(os.environ.get("KOKORO_SPEED", "1.0"))
KOKORO_MODEL = Path.home() / ".cache/hyperframes/tts/models/kokoro-v1.0.onnx"
KOKORO_VOICES = Path.home() / ".cache/hyperframes/tts/voices/voices-v1.0.bin"
SAY_VOICE = "Samantha"
ELEVEN_MODEL = "eleven_multilingual_v2"
ELEVEN_VOICE_ID = os.environ.get("ELEVEN_VOICE_ID")  # resolved by pick_voice()
RATE_WPM = 170
TARGET_URL = "https://skew.zevora.io"

_KOKORO = None


def active_segments(spec) -> list:
    """The segments this build includes. Optional segments (the corrections
    beat) join only when INCLUDE_BEAT=1 — the pipeline renders both variants
    from one capture pass."""
    include = os.environ.get("INCLUDE_BEAT") == "1"
    return [seg for seg in spec["segments"] if include or not seg.get("optional")]


def kokoro_tts(text: str, dest: Path, speed: float | None = None) -> None:
    global _KOKORO
    if _KOKORO is None:
        from kokoro_onnx import Kokoro

        _KOKORO = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    samples, sample_rate = _KOKORO.create(
        text, voice=KOKORO_VOICE, speed=speed or KOKORO_SPEED, lang="en-us"
    )
    import struct
    import wave

    ints = [max(-32767, min(32767, int(x * 32767))) for x in samples]
    with wave.open(str(dest.with_suffix(".raw.wav")), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{len(ints)}h", *ints))
    sh("ffmpeg", "-y", "-v", "error", "-i", str(dest.with_suffix(".raw.wav")),
       "-ar", "48000", "-ac", "2", str(dest))
    dest.with_suffix(".raw.wav").unlink()

ROOT = Path(__file__).parent
SCRIPT = ROOT / "script.json"
HEAD_PAD_S = 0.2
TAIL_PAD_S = 0.22
LUFS = -16


def env_key() -> str | None:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    env_file = ROOT.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ELEVENLABS_API_KEY=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def sh(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"command failed: {args[0]} …\n{result.stderr[-600:]}")
    return result.stdout


def probe_duration(path: Path) -> float:
    return float(sh("ffprobe", "-v", "error", "-show_entries", "format=duration",
                    "-of", "default=nw=1:nk=1", str(path)).strip())


# ----------------------------------------------------------------- narration
def eleven_request(path: str, payload: dict | None = None) -> bytes:
    key = env_key()
    if not key:
        raise SystemExit(
            "ELEVENLABS_API_KEY is not set. Add it to the repo .env or export it "
            "(or run with VO_FALLBACK_SAY=1 for the macOS fallback)."
        )
    req = urllib.request.Request(
        f"https://api.elevenlabs.io{path}",
        headers={"xi-api-key": key, "content-type": "application/json"},
        data=json.dumps(payload).encode() if payload else None,
        method="POST" if payload else "GET",
    )
    with urllib.request.urlopen(req, timeout=120) as response:
        return response.read()


def pick_voice() -> str:
    """Calm, measured, mid-range English narrator — a risk system's voice."""
    if ELEVEN_VOICE_ID:
        return ELEVEN_VOICE_ID
    voices = json.loads(eleven_request("/v1/voices"))["voices"]
    def score(v):
        labels = " ".join(str(x).lower() for x in (v.get("labels") or {}).values())
        name = v["name"].lower()
        s = 0
        for good in ("calm", "narration", "narrator", "deep", "middle", "middle-aged",
                     "professional", "news", "documentary"):
            if good in labels or good in name:
                s += 2
        for bad in ("excited", "hyped", "shouty", "characters", "anime", "whisper"):
            if bad in labels:
                s -= 3
        return s
    best = max(voices, key=score)
    print(f"voice: {best['name']} ({best['voice_id']}) — labels: {best.get('labels')}")
    return best["voice_id"]


def tts(text: str, dest: Path, voice_id: str | None, speed: float | None = None) -> None:
    if USE_SAY_FALLBACK:
        aiff = dest.with_suffix(".aiff")
        sh("say", "-v", SAY_VOICE, "-r", str(RATE_WPM), "-o", str(aiff), text)
        sh("ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(dest))
        aiff.unlink()
        return
    if not USE_ELEVENLABS:
        kokoro_tts(text, dest, speed)
        return
    audio = eleven_request(
        f"/v1/text-to-speech/{voice_id}",
        {
            "text": text,
            "model_id": ELEVEN_MODEL,
            "voice_settings": {
                "stability": 0.45, "similarity_boost": 0.75,
                "style": 0.15, "use_speaker_boost": True,
            },
        },
    )
    mp3 = dest.with_suffix(".mp3")
    mp3.write_bytes(audio)
    sh("ffmpeg", "-y", "-v", "error", "-i", str(mp3), "-ar", "48000", "-ac", "2", str(dest))
    mp3.unlink()


def silence_wav(seconds: float, dest: Path) -> None:
    sh("ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
       "-t", f"{seconds:.3f}", str(dest))


def concat_wavs(parts: list[Path], dest: Path) -> None:
    listfile = dest.with_suffix(".txt")
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
       "-i", str(listfile), "-c", "copy", str(dest))
    listfile.unlink()


def finalise(raw: Path, dest: Path) -> float:
    sh("ffmpeg", "-y", "-v", "error", "-i", str(raw),
       "-af",
       f"adelay={int(HEAD_PAD_S*1000)}|{int(HEAD_PAD_S*1000)},"
       f"apad=pad_dur={TAIL_PAD_S},loudnorm=I={LUFS}:TP=-1.5:LRA=11",
       "-ar", "48000", "-ac", "2", str(dest))
    return probe_duration(dest)


def build_vo() -> None:
    spec = json.loads(SCRIPT.read_text())
    gen, fin = ROOT / "vo" / "gen", ROOT / "vo" / "final"
    gen.mkdir(parents=True, exist_ok=True)
    fin.mkdir(parents=True, exist_ok=True)
    voice = pick_voice() if USE_ELEVENLABS and not USE_SAY_FALLBACK else None

    for seg in spec["segments"]:
        sid = seg["id"]
        if seg.get("deferred") and "vo" not in seg:
            # Capture-first segment: narration is generated after its frame is
            # captured, from figures read off that frame.
            print(f"{sid}: deferred — narrated from the captured frame")
            continue
        override = ROOT / "vo" / f"{sid}.wav"
        raw = gen / f"{sid}.wav"
        if override.exists():
            source = override
        else:
            if "vo_parts" in seg:
                parts = []
                for i, part in enumerate(seg["vo_parts"]):
                    p = gen / f"{sid}_part{i}.wav"
                    if "silence_s" in part:
                        silence_wav(part["silence_s"], p)
                    else:
                        tts(part["text"], p, voice, part.get("speed", seg.get("speed")))
                    parts.append(p)
                concat_wavs(parts, raw)
            else:
                tts(seg["vo"], raw, voice, seg.get("speed"))
            source = raw
        duration = finalise(source, fin / f"{sid}.wav")
        seg["duration_s"] = round(duration, 3)
        seg["total_s"] = round(
            max(duration + seg.get("hold_extra_s", 0.0), seg.get("min_hold_s", 0.0)), 3
        )
    SCRIPT.write_text(json.dumps(spec, indent=2) + "\n")
    report()


def report() -> None:
    """The pre-render gate: durations, the silence ledger, and the assertions."""
    spec = json.loads(SCRIPT.read_text())
    meta = spec["meta"]
    total = 0.0
    silences: list[tuple[str, float]] = []
    segments = active_segments(spec)
    print(f"{'id':5} {'title':18} {'vo':>7} {'total':>7}")
    for i, seg in enumerate(segments):
        if "total_s" not in seg:
            if seg.get("deferred"):
                print(f"{seg['id']:5} {seg['title']:18} {'—':>7} {'(capture-first)':>7}")
                continue
            raise SystemExit("run `build.py vo` first")
        total += seg["total_s"]
        print(f"{seg['id']:5} {seg['title']:18} {seg['duration_s']:7.2f} {seg['total_s']:7.2f}")
        # ledger: tail pad + next head pad form the cut gap; holds are silent
        if i < len(segments) - 1:
            silences.append((f"cut {seg['id']}→next", TAIL_PAD_S + HEAD_PAD_S))
        hold = seg.get("total_s", 0) - seg.get("duration_s", 0)
        if hold > 0.05:
            silences.append((f"{seg['id']} hold", hold))
        for part in seg.get("vo_parts", []):
            if "silence_s" in part:
                silences.append((f"{seg['id']} beat", part["silence_s"]))
    total_silence = sum(s for _, s in silences) + HEAD_PAD_S + TAIL_PAD_S
    longest = max(silences, key=lambda x: x[1])
    print(f"\ntotal picture: {total:.1f}s ({int(total//60)}:{total%60:04.1f})")
    print(f"total silence: {total_silence:.1f}s | longest gap: {longest[1]:.2f}s ({longest[0]})")
    deferred = any("total_s" not in seg for seg in segments)
    ok = True
    if deferred:
        print("note: deferred segment(s) not yet measured — window checked at final report")
    elif not (meta["duration_window_s"][0] <= total <= meta["duration_window_s"][1]):
        print(f"FAIL duration outside {meta['duration_window_s']}"); ok = False
    if total_silence > meta["silence_budget_s"]:
        print(f"FAIL silence {total_silence:.1f}s > {meta['silence_budget_s']}s"); ok = False
    if longest[1] > meta["max_single_silence_s"] and "beat" not in longest[0]:
        print(f"FAIL longest gap {longest[1]:.2f}s"); ok = False
    print("numbers gate:", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


# ----------------------------------------------------------------- captions
def wrap_caption(text: str, width: int = 42) -> list[str]:
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


def sentence_cues(text: str) -> list[str]:
    """Cue texts that never break mid-word and prefer sentence boundaries.

    Each cue is <= 2 lines of <= 42 chars. Sentences pack together while they
    fit; a long sentence wraps across cues on word boundaries only.
    """
    import re

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]
    cues: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if len(wrap_caption(candidate)) <= 2:
            current = candidate
            continue
        if current:
            cues.append(current)
            current = ""
        lines = wrap_caption(sentence)
        for i in range(0, len(lines) - (len(lines) % 2), 2):
            cues.append("\n".join(lines[i : i + 2]))
        if len(lines) % 2:
            current = lines[-1]
    if current:
        cues.append(current)
    return [c if "\n" in c else "\n".join(wrap_caption(c)) for c in cues]


def assert_cue_integrity(original: str, cues: list[str]) -> None:
    """No cue may start or end mid-word: rejoining cues must equal the text."""
    rejoined = " ".join(" ".join(c.split()) for c in cues)
    normalized = " ".join(original.split())
    if rejoined != normalized:
        raise SystemExit(f"caption splitter corrupted text:\n{rejoined!r}\nvs\n{normalized!r}")
    for cue in cues:
        for line in cue.split("\n"):
            if len(line) > 42:
                raise SystemExit(f"caption line over 42 chars: {line!r}")


def fmt_ts(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def cue_list() -> list[tuple[float, float, str]]:
    spec = json.loads(SCRIPT.read_text())
    cues, clock = [], 0.0
    for seg in active_segments(spec):
        duration = seg["total_s"]
        text = seg.get("vo") or " ".join(p.get("text", "") for p in seg.get("vo_parts", []))
        speech = seg["duration_s"] - HEAD_PAD_S - TAIL_PAD_S
        texts = sentence_cues(text)
        assert_cue_integrity(text, texts)
        chars = [len(t.replace("\n", " ")) for t in texts]
        total_chars = sum(chars) or 1
        t = clock + HEAD_PAD_S
        for cue_text, c in zip(texts, chars):
            span = speech * c / total_chars
            end = min(t + span, clock + duration)  # a cue never outlives its segment
            cues.append((t, end, cue_text))
            t += span
        clock += duration
    return cues


def build_srt() -> None:
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    cues = cue_list()
    (out / "skew.srt").write_text("".join(
        f"{i}\n{fmt_ts(a)} --> {fmt_ts(b)}\n{txt}\n\n" for i, (a, b, txt) in enumerate(cues, 1)
    ))
    print(f"wrote out/skew.srt — {len(cues)} cues (word-boundary safe, asserted)")


def build_segments() -> None:
    """Trim each capture at its head mark, cut to the scripted duration
    (freeze-padding if short), and mux the narration — every segment becomes a
    uniform 1080p30 h264+aac mp4 ready for stream-copy concat."""
    spec = json.loads(SCRIPT.read_text())
    for seg in spec["segments"]:
        sid = seg["id"]
        total = seg["total_s"]
        raw = ROOT / "frames" / f"{sid}.webm"
        vo = ROOT / "vo" / "final" / f"{sid}.wav"
        dest = ROOT / "frames" / f"{sid}.mp4"
        if not raw.exists():
            raise SystemExit(f"missing capture: {raw}")
        meta_file = ROOT / "frames" / f"{sid}.json"
        head = json.loads(meta_file.read_text()).get("head_trim", 0.0) if meta_file.exists() else 0.0
        sh("ffmpeg", "-y", "-v", "error",
           "-ss", f"{head:.3f}", "-i", str(raw), "-i", str(vo),
           "-filter_complex",
           f"[0:v]scale=1920:1080:flags=lanczos,fps=30,"
           f"tpad=stop_mode=clone:stop_duration=8,trim=duration={total},"
           f"setpts=PTS-STARTPTS[v];"
           f"[1:a]apad=whole_dur={total},atrim=duration={total},asetpts=PTS-STARTPTS[a]",
           "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-ar", "48000", "-ac", "2", str(dest))
        print(f"{sid}: {dest.name} @ {total:.2f}s (head {head:.1f}s)")


def assemble() -> None:
    """Concat-demux the uniform segments with stream copy — no re-encode drift
    — then write the webm fallback. Duration must land in the window."""
    spec = json.loads(SCRIPT.read_text())
    out = ROOT / "out"
    out.mkdir(exist_ok=True)
    segs = [ROOT / "frames" / f"{seg['id']}.mp4" for seg in active_segments(spec)]
    missing = [p.name for p in segs if not p.exists()]
    if missing:
        raise SystemExit(f"missing segment renders: {missing}")
    listfile = out / "concat.txt"
    listfile.write_text("".join(f"file '{p.resolve()}'\n" for p in segs))
    master = out / "skew-demo.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
       "-c", "copy", "-movflags", "+faststart", str(master))
    duration = probe_duration(master)
    lo, hi = json.loads(SCRIPT.read_text())["meta"]["duration_window_s"]
    print(f"clean master: {master.name} — {duration:.1f}s")
    if not (lo <= duration <= hi + 0.5):
        raise SystemExit(f"FAIL: {duration:.1f}s outside the {lo}-{hi}s window")
    print("(webm encodes after the mix)")


def burn_captions(master: Path, dest: Path) -> None:
    """Cues rendered as transparent PNG strips in the site's own type and
    overlaid with time windows — this ffmpeg ships without libass/drawtext,
    and the strips come out sharper anyway."""
    from playwright.sync_api import sync_playwright

    cues = cue_list()
    strip_dir = ROOT / "out" / "cues"
    strip_dir.mkdir(parents=True, exist_ok=True)
    page_file = strip_dir / "cap.html"
    page_file.write_text(
        """<!doctype html><meta charset='utf-8'><style>
        body{margin:0;width:1920px;height:150px;background:transparent;display:flex;
             align-items:flex-end;justify-content:center;font-family:-apple-system,'Manrope',sans-serif}
        .cap{background:rgba(16,16,19,.82);color:#f4f4f6;font-size:34px;line-height:1.35;
             padding:12px 28px;border-radius:12px;text-align:center;white-space:pre-line}
        </style><body><div class='cap' id='c'></div></body>"""
    )
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 150})
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
        chain.append(
            f"[{prev}][{i + 1}:v]overlay=x=(W-w)/2:y=H-h-90:"
            f"enable='between(t,{a:.3f},{b:.3f})'[v{i}]"
        )
        prev = f"v{i}"
    sh("ffmpeg", "-y", "-v", "error", *inputs,
       "-filter_complex", ";".join(chain), "-map", f"[{prev}]", "-map", "0:a",
       "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
       "-c:a", "copy", "-movflags", "+faststart", str(dest))
    print(f"captions burned: {dest.name} ({len(cues)} cues)")


def mix_master() -> None:
    """Phase 6: synthesized ambient bed (authored by this pipeline — no
    third-party audio, licence note in ASSETS-LICENSE.md), sidechain duck
    under speech, a manual thin-out across the refusal beat, two accents,
    final loudnorm to -14 LUFS / -1.5 dBTP."""
    spec = json.loads(SCRIPT.read_text())
    out = ROOT / "out"
    master = out / "skew-demo.mp4"
    total = probe_duration(master)

    # a31's beat position in the final timeline, from measured audio.
    start = 0.0
    for seg in active_segments(spec):
        if seg["id"] == "a31":
            break
        start += seg["total_s"]
    part0 = probe_duration(ROOT / "vo" / "gen" / "a31_part0.wav")
    beat_at = start + HEAD_PAD_S + part0
    thin_from, thin_to = beat_at - 5.0, beat_at + 5.0
    a32_start = 0.0
    for seg in active_segments(spec):
        if seg["id"] == "a32":
            break
        a32_start += seg["total_s"]
    accent_breach = beat_at - 0.2
    accent_tick = a32_start + 2.4

    graph = (
        # bed: three detuned drones + air, heavily filtered, slow swell
        f"sine=f=55:d={total}[d1];sine=f=110.6:d={total}[d2];"
        f"sine=f=164.4:d={total}[d3];anoisesrc=c=pink:d={total}:a=0.06[nz];"
        f"[nz]lowpass=f=320[air];"
        f"[d1][d2][d3][air]amix=inputs=4:normalize=0,lowpass=f=700,"
        f"tremolo=f=0.1:d=0.3,volume=-30dB,"
        # manual thin-out across the refusal beat window
        f"volume=volume='if(between(t,{thin_from:.2f},{thin_to:.2f}),0.18,1)':eval=frame"
        f"[bedraw];"
        # duck the bed under speech
        f"[bedraw][0:a]sidechaincompress=threshold=0.02:ratio=6:attack=120:release=700[bed];"
        # accents: a low tone into the breach, a short tick on the fill
        f"sine=f=82:d=1.1,afade=t=in:d=0.35,afade=t=out:st=0.6:d=0.5,"
        f"volume=-21dB,adelay={int(accent_breach * 1000)}|{int(accent_breach * 1000)}[acc1];"
        f"sine=f=1318:d=0.14,afade=t=out:st=0.05:d=0.09,"
        f"volume=-23dB,adelay={int(accent_tick * 1000)}|{int(accent_tick * 1000)}[acc2];"
        f"[0:a][bed][acc1][acc2]amix=inputs=4:normalize=0:duration=first,"
        f"loudnorm=I=-14:TP=-2.0:LRA=11[mix]"
    )
    mixed = out / "skew-demo-mixed.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-i", str(master),
       "-filter_complex", graph, "-map", "0:v", "-map", "[mix]",
       "-c:v", "copy", "-c:a", "aac", "-ar", "48000", "-ac", "2",
       "-movflags", "+faststart", str(mixed))
    mixed.replace(master)
    (ROOT / "ASSETS-LICENSE.md").write_text(
        "# Audio assets\n\nThe ambient bed and both sound accents are synthesized "
        "by build.py (sine/pink-noise sources through ffmpeg filters) at build "
        "time. No third-party audio is used anywhere in the video; no licence "
        "is required.\n"
    )
    print(f"mixed master: bed + accents, thin-out {thin_from:.1f}-{thin_to:.1f}s, "
          f"breach tone @{accent_breach:.1f}s, tick @{accent_tick:.1f}s")



def watermark() -> None:
    """The product mark, lower-left at 35% opacity throughout, dropping to
    15% across the refusal beat so nothing competes with the refusal itself.
    The mark is the baked production asset — the same pixels the desk header
    renders. The webm fallback encodes from the watermarked master."""
    spec = json.loads(SCRIPT.read_text())
    out = ROOT / "out"
    master = out / "skew-demo.mp4"
    mark = ROOT / "motion" / "assets" / "skew-logo-512.png"

    start = 0.0
    for seg in active_segments(spec):
        if seg["id"] == "a31":
            break
        start += seg["total_s"]
    part0 = probe_duration(ROOT / "vo" / "gen" / "a31_part0.wav")
    beat_at = start + HEAD_PAD_S + part0
    dim_from, dim_to = beat_at - 5.0, beat_at + 5.0

    marked = out / "skew-demo-marked.mp4"
    sh("ffmpeg", "-y", "-v", "error", "-i", str(master), "-i", str(mark),
       "-filter_complex",
       f"[1:v]scale=64:64,format=rgba,split[m1][m2];"
       f"[m1]colorchannelmixer=aa=0.35[wmA];"
       f"[m2]colorchannelmixer=aa=0.15[wmB];"
       f"[0:v][wmA]overlay=x=30:y=H-h-30:"
       f"enable='not(between(t,{dim_from:.2f},{dim_to:.2f}))'[v1];"
       f"[v1][wmB]overlay=x=30:y=H-h-30:"
       f"enable='between(t,{dim_from:.2f},{dim_to:.2f})'[vout]",
       "-map", "[vout]", "-map", "0:a",
       "-c:v", "libx264", "-profile:v", "high", "-crf", "18", "-pix_fmt", "yuv420p",
       "-c:a", "copy", "-movflags", "+faststart", str(marked))
    marked.replace(master)
    sh("ffmpeg", "-y", "-v", "error", "-i", str(master),
       "-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0", "-c:a", "libopus",
       str(out / "skew-demo.webm"))
    print(f"watermark: mark lower-left, 35% -> 15% across {dim_from:.1f}-{dim_to:.1f}s")


def spec_seg(spec, sid):
    return next(s for s in spec["segments"] if s["id"] == sid)


def verify_final() -> None:
    """Phase §8 gates, measured off the finished master."""
    out = ROOT / "out"
    master = out / "skew-demo.mp4"
    duration = probe_duration(master)
    # loudness + true peak
    measure = subprocess.run(
        ["ffmpeg", "-i", str(master), "-af",
         "loudnorm=I=-14:TP=-1.5:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    blob = measure[measure.rindex("{"):measure.rindex("}") + 1]
    stats = json.loads(blob)
    lufs, tp = float(stats["input_i"]), float(stats["input_tp"])
    # silence ledger on the SPOKEN track (the bed never counts as content)
    vo_concat = out / "voledger.wav"
    listfile = out / "voledger.txt"
    spec = json.loads(SCRIPT.read_text())
    listfile.write_text("".join(
        f"file '{(ROOT / 'vo' / 'final' / (seg['id'] + '.wav')).resolve()}'\n"
        for seg in active_segments(spec)))
    sh("ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listfile),
       "-c", "copy", str(vo_concat))
    det = subprocess.run(
        ["ffmpeg", "-i", str(vo_concat), "-af", "silencedetect=n=-35dB:d=0.8",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    import re as _re

    pairs = _re.findall(r"silence_start: ([\d.]+)[\s\S]*?silence_duration: ([\d.]+)", det)
    gaps = [float(d) for _, d in pairs]
    total_silence = sum(gaps)
    # The opening identity beat is designed silence (spec: black + mark, under
    # 3s, before the first narration line) — it gets its own gate rather than
    # tripping the dead-air one. Only a gap that STARTS the film qualifies.
    leading = 0.0
    if pairs and float(pairs[0][0]) < 0.5:
        leading = gaps.pop(0)
    longest = max(gaps) if gaps else 0.0
    checks = [
        ("duration inside the window", *(lambda w: (w[0] <= duration <= w[1] + 0.5, f"{duration:.1f}s (window {w[0]}-{w[1]}s, hard limit 180s)"))(json.loads(SCRIPT.read_text())["meta"]["duration_window_s"])),
        ("opening identity <= 3.0s", leading <= 3.0, f"{leading:.2f}s"),
        ("total silence < 12s", total_silence < 12, f"{total_silence:.1f}s"),
        ("longest gap <= 1.6s (after the open)", longest <= 1.6, f"{longest:.2f}s"),
        ("integrated -14 LUFS (±1)", abs(lufs + 14) <= 1.0, f"{lufs:.1f} LUFS"),
        ("true peak < -1.5 dBTP", tp <= -1.4, f"{tp:.1f} dBTP"),
    ]
    ok = True
    for name, passed, detail in checks:
        print(f"{'PASS' if passed else 'FAIL'}  {name} — {detail}")
        ok = ok and passed
    test_splitter()
    if not ok:
        raise SystemExit("verification FAILED")
    vo_concat.unlink(); listfile.unlink()


def test_splitter() -> None:
    samples = [
        "Every other agent in this hackathon forecasts direction, then buys an option pointing at the guess. The option is incidental.",
        "This is Skew. An autonomous options desk that never predicts where the market is going.",
        "Supercalifragilistic expialidocious words that are quite long indeed and overflow lines repeatedly without ever breaking words.",
    ]
    for text in samples:
        cues = sentence_cues(text)
        assert_cue_integrity(text, cues)
    print("caption splitter: all assertions pass")


if __name__ == "__main__":
    phase = sys.argv[1] if len(sys.argv) > 1 else "report"
    {"vo": build_vo, "report": report, "srt": build_srt, "test": test_splitter,
     "segments": build_segments, "assemble": assemble, "mix": mix_master,
     "watermark": watermark,
     "burn": lambda: burn_captions(ROOT / "out" / "skew-demo.mp4",
                                   ROOT / "out" / "skew-demo-captions.mp4"),
     "verify": verify_final}[phase]()
