#!/bin/sh
# Starts an installed Play it Slowly on a test tone for a few seconds and fails on any error.
# Usage: packaging/smoke-test.sh <command that runs playitslowly>...
set -u
dir=$(mktemp -d)
python3 - "$dir/tone.wav" <<'EOF'
import math, struct, sys, wave
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(b"".join(struct.pack("<hh", int(8000 * math.sin(i / 20)), 0) for i in range(44100 * 3)))
EOF
export HOME="$dir"
# CI runners set their own config folder, so point it into the test home; SMOKE_CONFIG_REL overrides where to look inside it.
export XDG_CONFIG_HOME="$dir/.config"
config="$dir/${SMOKE_CONFIG_REL:-.config/playitslowly.json}"
timeout 20 xvfb-run -a "$@" --sink=fakesink "$dir/tone.wav" > "$dir/log" 2>&1
status=$?
cat "$dir/log"
# timeout's 124 means the app was still running, which is what a healthy start looks like.
if [ "$status" -ne 124 ]; then
    echo "smoke test: expected the app to keep running, but it exited with $status" >&2
    exit 1
fi
if grep -qE "Traceback|Waveform load error|CRITICAL|GStreamer error" "$dir/log"; then
    echo "smoke test: errors in the output" >&2
    exit 1
fi
if ! grep -q '"duration": 3' "$config" 2>/dev/null; then
    echo "smoke test: the test tone was not loaded; config was:" >&2; cat "$config" >&2 2>/dev/null
    exit 1
fi
echo "smoke test: passed"
