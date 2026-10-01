# playitslowly/waveform.py
"""
WaveformExtractor: detailed waveform generator for Play it Slowly.

- Decodes with GStreamer, so it reads every format the player can play.
- Computes min/max amplitude envelopes for Cool Edit–style waveforms.
"""

import numpy as np

from gi.repository import Gst

# Samples per second kept for the waveform; plenty for drawing and much less to hold in memory.
WAVEFORM_RATE = 4000


class WaveformExtractor:
    def __init__(self, uri):
        """decode uri to mono samples; runs in a background thread and blocks until the file is read"""
        pipeline = Gst.Pipeline()
        playbin = Gst.ElementFactory.make("playbin")
        pipeline.add(playbin)
        playbin.set_property("uri", uri)
        playbin.set_property("video-sink", Gst.ElementFactory.make("fakesink"))
        sink = Gst.parse_bin_from_description(
            "audioconvert ! audioresample ! audio/x-raw,format=F32LE,channels=1,rate=%d ! appsink name=sink sync=false" % WAVEFORM_RATE, True)
        playbin.set_property("audio-sink", sink)
        appsink = sink.get_by_name("sink")
        chunks = []
        pipeline.set_state(Gst.State.PLAYING)
        try:
            while True:
                sample = appsink.emit("try-pull-sample", 10 * Gst.SECOND)
                if sample is None:
                    break
                buffer = sample.get_buffer()
                ok, info = buffer.map(Gst.MapFlags.READ)
                if ok:
                    chunks.append(np.frombuffer(info.data, dtype=np.float32).copy())
                    buffer.unmap(info)
            error = pipeline.get_bus().pop_filtered(Gst.MessageType.ERROR)
            if error:
                raise RuntimeError(error.parse_error()[0].message)
        finally:
            pipeline.set_state(Gst.State.NULL)
        samples = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)

        # Normalize to [-1, 1]
        max_amp = np.max(np.abs(samples)) if samples.size else 0
        self.samples = samples / max_amp if max_amp > 0 else samples
        self.sample_rate = WAVEFORM_RATE

    def get_samples(self, num_points=20000):
        """
        Return an interleaved min/max envelope array of roughly num_points length.
        This gives DAW-style visual richness.
        """
        samples = self.samples
        total = len(samples)
        if total == 0:
            return np.zeros(num_points, dtype=np.float32)

        # Compute window size; more points => more detail
        step = max(1, total // num_points)
        trimmed = samples[: step * (total // step)]
        reshaped = trimmed.reshape(-1, step)

        # Get per-window min and max
        mins = reshaped.min(axis=1)
        maxs = reshaped.max(axis=1)

        # Interleave for drawing: [min0, max0, min1, max1, ...]
        out = np.empty(mins.size * 2, dtype=np.float32)
        out[0::2] = mins
        out[1::2] = maxs

        # Slight smoothing to make waveform more visually natural
        out = np.convolve(out, np.ones(3)/3, mode='same')

        return out
