"""Checks the audio side of an installed Play it Slowly without opening its window: effects, playback and waveform."""

import math
import os
import struct
import sys
import tempfile
import wave

from playitslowly import app  # noqa: F401  sets up GStreamer the way the app does
from playitslowly.pipeline import Pipeline
from playitslowly.waveform import WaveformExtractor
from gi.repository import Gst
import numpy  # noqa: F401
import yt_dlp  # noqa: F401

path = os.path.join(tempfile.mkdtemp(), "tone.wav")
with wave.open(path, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(44100)
    w.writeframes(b"".join(struct.pack("<hh", int(8000 * math.sin(i / 20)), 0) for i in range(44100 * 2)))
uri = "file://" + path

pipeline = Pipeline("fakesink")
pipeline.set_balance("midside", -0.5)
pipeline.set_speed(0.75)
pipeline.set_file(uri)
pipeline.pause()
result = pipeline.get_state(10 * Gst.SECOND)[0]
if result != Gst.StateChangeReturn.SUCCESS:
    sys.exit("the effects pipeline did not start: %s" % result)
samples = WaveformExtractor(uri).get_samples(1000)
if len(samples) == 0:
    sys.exit("the waveform is empty")
print("pipeline check: passed")
