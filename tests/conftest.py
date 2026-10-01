"""Shared helpers: generated test audio, a main window that plays into a silent sink, and a main loop runner."""

import math
import os
import struct
import sys
import time
import wave

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playitslowly import app  # noqa: E402  imports GTK and GStreamer the way the app does
from gi.repository import Gdk, GLib, Gst, GstPbutils, Gtk  # noqa: E402

# Uncaught errors in callbacks are collected here, so a test fails instead of a crash dialog blocking it.
ERRORS = []
sys.excepthook = lambda etype, value, tb: ERRORS.append((etype, value))


def run_until(condition, timeout=10.0):
    """run the main loop until condition() is true or the timeout passes; returns the last result"""
    context = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        while context.pending():
            context.iteration(False)
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def wait(seconds):
    run_until(lambda: False, seconds)


def write_tone(path, seconds, left=0.25, right=0.0, rate=44100):
    """a 16 bit stereo wav with a 440 Hz tone at the given amplitude on each side"""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for i in range(int(seconds * rate)):
            value = math.sin(2 * math.pi * 440 * i / rate)
            frames += struct.pack("<hh", int(32767 * left * value), int(32767 * right * value))
        w.writeframes(bytes(frames))
    return str(path)


def encode(path, seconds, encoder, title=None, artist=None):
    """encode a tone with a GStreamer encoder description, optionally tagged"""
    tags = ""
    if title:
        tags = "! taginject tags=\"title=\\\"%s\\\",artist=\\\"%s\\\"\" " % (title, artist)
    description = ("audiotestsrc wave=sine freq=330 num-buffers=%d samplesperbuffer=1024 ! audio/x-raw,rate=44100,channels=2 "
                   "! audioconvert ! audioresample %s! %s ! filesink location=\"%s\"") % (int(seconds * 44100 / 1024), tags, encoder, path)
    pipeline = Gst.parse_launch(description)
    pipeline.set_state(Gst.State.PLAYING)
    pipeline.get_bus().timed_pop_filtered(60 * Gst.SECOND, Gst.MessageType.EOS | Gst.MessageType.ERROR)
    pipeline.set_state(Gst.State.NULL)
    return str(path)


def uri(path):
    return GLib.filename_to_uri(str(path), None)


def decode(path):
    """the decoded samples of a file as a (frames, 2) float array"""
    pipeline = Gst.Pipeline()
    playbin = Gst.ElementFactory.make("playbin")
    pipeline.add(playbin)
    playbin.set_property("uri", uri(path))
    sink = Gst.parse_bin_from_description(
        "audioconvert ! audio/x-raw,format=F32LE,channels=2,rate=44100 ! appsink name=sink sync=false", True)
    playbin.set_property("audio-sink", sink)
    appsink = sink.get_by_name("sink")
    chunks = []
    pipeline.set_state(Gst.State.PLAYING)
    while True:
        sample = appsink.emit("try-pull-sample", 10 * Gst.SECOND)
        if sample is None:
            break
        buffer = sample.get_buffer()
        ok, info = buffer.map(Gst.MapFlags.READ)
        chunks.append(np.frombuffer(info.data, dtype=np.float32).copy())
        buffer.unmap(info)
    pipeline.set_state(Gst.State.NULL)
    return np.concatenate(chunks).reshape(-1, 2)


def peak_db(samples):
    """the peak level of each channel in dBFS"""
    peaks = np.max(np.abs(samples), axis=0)
    return [20 * math.log10(p) if p > 0 else -200.0 for p in peaks]


def discover(path):
    return GstPbutils.Discoverer.new(10 * Gst.SECOND).discover_uri(uri(path))


def key(window, name, ctrl=False, release=False):
    """send a key press (or release) straight to the window's handler"""
    event = Gdk.Event.new(Gdk.EventType.KEY_RELEASE if release else Gdk.EventType.KEY_PRESS)
    event.keyval = Gdk.keyval_from_name(name)
    event.state = Gdk.ModifierType.CONTROL_MASK if ctrl else 0
    return (window.key_release if release else window.key_press)(window, event)


def position(window):
    ok, value = window.pipeline.playbin.query_position(Gst.Format.TIME)
    return window.pipeline.song_time(value) if ok else None


@pytest.fixture(scope="session")
def audio(tmp_path_factory):
    """generated test files: a left-only tone, a loud tone, a long tone, and tagged mp3 and opus files"""
    folder = tmp_path_factory.mktemp("audio")
    return {
        "left": write_tone(folder / "left.wav", 6),
        "loud": write_tone(folder / "loud.wav", 2, left=0.99, right=0.99),
        "long": write_tone(folder / "long.wav", 40),
        "mp3": encode(folder / "tagged.mp3", 4, "lamemp3enc ! id3v2mux", title="Practice Tune", artist="Test Band"),
        "opus": encode(folder / "tone.opus", 4, "opusenc ! oggmux"),
    }


@pytest.fixture
def window(tmp_path):
    """a main window playing into a clock-synced silent sink, with its own config file"""
    ERRORS.clear()
    win = app.MainWindow("fakesink sync=true", app.Config(str(tmp_path / "playitslowly.json")))
    win.show_all()
    yield win
    for export in list(win.pipeline.exports):
        export.stop()
    win.play_button.set_active(False)
    win.pipeline.set_state(Gst.State.NULL)
    for toplevel in Gtk.Window.list_toplevels():
        if toplevel.get_title() == "Error":
            toplevel.destroy()
    win.hide()
    assert not ERRORS, "uncaught errors in callbacks: %r" % ERRORS


def open_file(win, path, timeout=10):
    """open a file and wait until its duration is known"""
    win.set_uri(uri(path))
    assert run_until(lambda: win.endchooser.get_adjustment().get_upper() > 1.0, timeout), "the file did not load"
