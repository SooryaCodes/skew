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
USE_SAY_FALLBACK = os.environ.get("VO_FALLBACK_SAY") == "1"
SAY_VOICE = "Samantha"
ELEVEN_MODEL = "eleven_multilingual_v2"
ELEVEN_VOICE_ID = os.environ.get("ELEVEN_VOICE_ID")  # resolved by pick_voice()
RATE_WPM = 170
TARGET_URL = "https://skew.zevora.io"

ROOT = Path(__file__).parent
SCRIPT = ROOT / "script.json"
HEAD_PAD_S = 0.25
TAIL_PAD_S = 0.35
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


def tts(text: str, dest: Path, voice_id: str) -> None:
    if USE_SAY_FALLBACK:
        aiff = dest.with_suffix(".aiff")
        sh("say", "-v", SAY_VOICE, "-r", str(RATE_WPM), "-o", str(aiff), text)
        sh("ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", "48000", "-ac", "2", str(dest))
        aiff.unlink()
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
    voice = None if USE_SAY_FALLBACK else pick_voice()

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
                        tts(part["text"], p, voice)
                    parts.append(p)
                concat_wavs(parts, raw)
            else:
                tts(seg["vo"], raw, voice)
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
    print(f"{'id':5} {'title':18} {'vo':>7} {'total':>7}")
    for i, seg in enumerate(spec["segments"]):
        if "total_s" not in seg:
            if seg.get("deferred"):
                print(f"{seg['id']:5} {seg['title']:18} {'—':>7} {'(capture-first)':>7}")
                continue
            raise SystemExit("run `build.py vo` first")
        total += seg["total_s"]
        print(f"{seg['id']:5} {seg['title']:18} {seg['duration_s']:7.2f} {seg['total_s']:7.2f}")
        # ledger: tail pad + next head pad form the cut gap; holds are silent
        if i < len(spec["segments"]) - 1:
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
    deferred = any("total_s" not in seg for seg in spec["segments"])
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
    for seg in spec["segments"]:
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
    {"vo": build_vo, "report": report, "srt": build_srt, "test": test_splitter}[phase]()
