#!/bin/bash
# Post-close pipeline: one capture pass, two finished masters.
#   A (canonical): out/skew-demo.mp4 / -captions.mp4 / .webm  — no beat
#   B:             out/skew-demo-correction-beat*.{mp4,webm}  — with a31c
# Fails loudly at any gate; variant B failing its window is reported, not fatal.
set -e
cd "$(dirname "$0")"

echo "=== CAPTURE (all segments) ==="
python3 capture.py

echo "=== VARIANT A: no beat ==="
unset INCLUDE_BEAT
python3 build.py vo
python3 build.py test
python3 build.py segments
python3 build.py assemble
python3 build.py mix
python3 build.py verify
python3 build.py burn
mkdir -p out/variant-a
cp out/skew-demo.mp4 out/skew-demo-captions.mp4 out/skew-demo.webm out/variant-a/

echo "=== VARIANT B: with the corrections beat ==="
export INCLUDE_BEAT=1
if python3 build.py assemble; then
  python3 build.py mix
  if python3 build.py verify; then B_VERIFY=pass; else B_VERIFY=fail; fi
  python3 build.py burn
  mv out/skew-demo.mp4 out/skew-demo-correction-beat.mp4
  mv out/skew-demo-captions.mp4 out/skew-demo-correction-beat-captions.mp4
  mv out/skew-demo.webm out/skew-demo-correction-beat.webm
  echo "variant B verify: ${B_VERIFY}"
else
  echo "variant B: FAILED the duration window at assemble — not produced"
fi

# restore canonical variant A names
cp out/variant-a/skew-demo.mp4 out/skew-demo.mp4
cp out/variant-a/skew-demo-captions.mp4 out/skew-demo-captions.mp4
cp out/variant-a/skew-demo.webm out/skew-demo.webm

echo "=== DONE ==="
ls -la out/*.mp4 out/*.webm
