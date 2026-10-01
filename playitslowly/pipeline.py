"""
Author: Jonas Wagner

Play it Slowly
Copyright (C) 2009 - 2015 Jonas Wagner

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys

argv = sys.argv
# work around Gstreamer parsing sys.argv!
sys.argv = []

import gi
gi.require_version('Gst', '1.0')

from gi.repository import Gst
sys.argv = argv

from playitslowly import myGtk

_ = lambda x: x

import os

# Each balance mode maps a value from -1 to 1 onto a 2x2 matrix: rows are the left and right outputs, columns the left and right inputs.
BALANCE_MODES = [
    ("stereo", _("Stereo")),
    ("leftright", _("Left / Right")),
    ("balance", _("Balance (mono at the ends)")),
    ("midside", _("Mid / Side")),
]

# Export formats picked by the file extension; each is a GStreamer encoder description.
ENCODERS = {
    ".wav": "wavenc",
    ".mp3": "lamemp3enc target=bitrate bitrate=192 cbr=true ! id3v2mux",
    ".ogg": "vorbisenc quality=0.6 ! oggmux",
    ".flac": "flacenc",
}

LIMITER_THRESHOLD = 0.89 # about -1 dBFS
LIMITER_RATIO = 0.1


def balance_matrix(mode, value):
    """return the 2x2 channel matrix for a balance mode and a value from -1 to 1"""
    v = max(-1.0, min(1.0, value))
    if mode == "leftright":
        # Fade one side out while the other stays at full level.
        return [[min(1.0, 1.0 - v), 0.0], [0.0, min(1.0, 1.0 + v)]]
    if mode == "balance":
        # At the ends both speakers play the one channel in mono.
        if v <= 0:
            return [[1.0, 0.0], [-v, 1.0 + v]]
        return [[1.0 - v, v], [0.0, 1.0]]
    if mode == "midside":
        # -1 keeps only the middle (usually vocals), 1 keeps only what differs between the sides.
        mid = 1.0 - max(v, 0.0)
        side = 1.0 + min(v, 0.0)
        a, b = (mid + side) / 2, (mid - side) / 2
        return [[a, b], [b, a]]
    return [[1.0, 0.0], [0.0, 1.0]]


def matrix_string(matrix):
    return "<" + ",".join("<" + ",".join("(double)%r" % float(x) for x in row) + ">" for row in matrix) + ">"


class Effects:
    """pitch and tempo, then balance and limiter, as a chain of elements inside a bin"""
    def __init__(self, bin):
        self.speedchanger = Gst.ElementFactory.make("pitch")
        if self.speedchanger is None:
            myGtk.show_error(_("You need to install the Gstreamer soundtouch elements for "
                    "play it slowly too. They are part of Gstreamer-plugins-bad. Consult the "
                    "README if you need more information.")).run()
            raise SystemExit()
        convert = Gst.ElementFactory.make("audioconvert")
        # The balance matrix needs exactly two channels, so mono and surround files are converted first.
        caps = Gst.ElementFactory.make("capsfilter")
        caps.set_property("caps", Gst.Caps.from_string("audio/x-raw,format=F32LE,channels=2"))
        self.matrix = Gst.ElementFactory.make("audiomixmatrix")
        self.matrix.set_property("in-channels", 2)
        self.matrix.set_property("out-channels", 2)
        self.matrix.set_property("channel-mask", 0x3)
        self.limiter = Gst.ElementFactory.make("audiodynamic")
        self.limiter.set_property("characteristics", "hard-knee")
        self.limiter.set_property("mode", "compressor")
        self.limiter.set_property("threshold", LIMITER_THRESHOLD)
        self.last = Gst.ElementFactory.make("audioconvert")
        # The matrix must be valid before linking, or the element refuses to negotiate.
        self.set_balance("stereo", 0.0)
        self.set_limiter(True)
        chain = [self.speedchanger, convert, caps, self.matrix, self.limiter, self.last]
        for element in chain:
            bin.add(element)
        for a, b in zip(chain, chain[1:]):
            a.link(b)
        bin.add_pad(Gst.GhostPad.new("sink", self.speedchanger.get_static_pad("sink")))

    def set_balance(self, mode, value):
        self.balance = (mode, value)
        Gst.util_set_object_arg(self.matrix, "matrix", matrix_string(balance_matrix(mode, value)))

    def set_limiter(self, enabled):
        self.limiter_enabled = enabled
        # A ratio of 1 passes the signal through unchanged.
        self.limiter.set_property("ratio", LIMITER_RATIO if enabled else 1.0)

    def copy_settings_from(self, other):
        for name in ("tempo", "pitch"):
            self.speedchanger.set_property(name, other.speedchanger.get_property(name))
        self.set_balance(*other.balance)
        self.set_limiter(other.limiter_enabled)


class Pipeline(Gst.Pipeline):
    def __init__(self, sink):
        Gst.Pipeline.__init__(self)
        self.playbin = Gst.ElementFactory.make("playbin")
        self.add(self.playbin)

        bin = Gst.Bin()
        self.effects = Effects(bin)
        self.speedchanger = self.effects.speedchanger

        self.audiosink = Gst.parse_launch(sink)
        bin.add(self.audiosink)
        self.effects.last.link(self.audiosink)
        self.playbin.set_property("audio-sink", bin)
        bus = self.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

        self.eos = lambda: None
        self.tags = lambda taglist: None
        self.error_shown = False
        self.exports = []
    def on_message(self, bus, message):
        t = message.type
        if t == Gst.MessageType.EOS:
            self.eos()
        elif t == Gst.MessageType.TAG:
            self.tags(message.parse_tag())
        elif t == Gst.MessageType.ERROR:
            # One broken file posts several errors, so show only the first.
            if not self.error_shown:
                self.error_shown = True
                myGtk.show_error("Gstreamer error: %s - %s" % message.parse_error())

    def set_volume(self, volume):
        self.playbin.set_property("volume", volume)

    def set_speed(self, speed):
        self.speedchanger.set_property("tempo", speed)

    def get_speed(self):
        return self.speedchanger.get_property("tempo")

    def pipe_time(self, t):
        """convert from song position to pipeline time"""
        return t/self.get_speed()*1000000000

    def song_time(self, t):
        """convert from pipetime time to song position"""
        return t*self.get_speed()/1000000000

    def set_pitch(self, pitch):
        self.speedchanger.set_property("pitch", pitch)

    def set_balance(self, mode, value):
        self.effects.set_balance(mode, value)

    def set_limiter(self, enabled):
        self.effects.set_limiter(enabled)

    def save_file(self, source_uri, path, done, section=None):
        """render source_uri with the current settings into path, encoded by its extension

        section is an optional (start, end) in song seconds; done(error) is called when it finishes.
        """
        encoder = ENCODERS.get(os.path.splitext(path)[1].lower(), ENCODERS[".wav"])
        pipeline = Gst.Pipeline()
        playbin = Gst.ElementFactory.make("playbin")
        pipeline.add(playbin)
        playbin.set_property("uri", source_uri)
        # Video in the source file is dropped instead of opening a window.
        playbin.set_property("video-sink", Gst.ElementFactory.make("fakesink"))

        bin = Gst.Bin()
        effects = Effects(bin)
        effects.copy_settings_from(self.effects)
        encode = Gst.parse_bin_from_description(encoder, True)
        filesink = Gst.ElementFactory.make("filesink")
        filesink.set_property("location", path)
        bin.add(encode)
        bin.add(filesink)
        effects.last.link(encode)
        encode.link(filesink)
        playbin.set_property("audio-sink", bin)
        export = Export(self, pipeline, path, done, section, self.get_speed())
        self.exports.append(export)
        # A section needs a seek once the file is open, so it starts paused.
        pipeline.set_state(Gst.State.PAUSED if section else Gst.State.PLAYING)
        return export

    def set_file(self, uri):
        self.error_shown = False
        self.playbin.set_property("uri", uri)

    def play(self):
        self.set_state(Gst.State.PLAYING)

    def pause(self):
        self.set_state(Gst.State.PAUSED)

    def reset(self):
        self.set_state(Gst.State.READY)




class Export:
    """one running export: progress() goes from 0 to 1, cancel() stops it and deletes the partial file"""
    def __init__(self, owner, pipeline, path, done, section, speed):
        self.owner = owner
        self.pipeline = pipeline
        self.path = path
        self.done = done
        self.speed = speed
        # Seek positions are in output time, which runs faster or slower than the song by the speed.
        self.section = tuple(int(t / speed * Gst.SECOND) for t in section) if section else None
        self.seeked = False
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self.on_message)

    def on_message(self, bus, message):
        if message.type == Gst.MessageType.ASYNC_DONE and self.section and not self.seeked:
            self.seeked = True
            start, end = self.section
            self.pipeline.seek(1.0, Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.ACCURATE,
                    Gst.SeekType.SET, start, Gst.SeekType.SET, end)
            self.pipeline.set_state(Gst.State.PLAYING)
        elif message.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
            error = message.parse_error()[0].message if message.type == Gst.MessageType.ERROR else None
            self.stop()
            self.done(error)

    def progress(self):
        ok_position, position = self.pipeline.query_position(Gst.Format.TIME)
        if not ok_position:
            return 0.0
        if self.section:
            start, end = self.section
        else:
            ok_duration, end = self.pipeline.query_duration(Gst.Format.TIME)
            start = 0
            if not ok_duration:
                return 0.0
        return max(0.0, min(1.0, (position - start) / max(1, end - start)))

    def stop(self):
        self.pipeline.get_bus().remove_signal_watch()
        self.pipeline.set_state(Gst.State.NULL)
        if self in self.owner.exports:
            self.owner.exports.remove(self)

    def cancel(self):
        self.stop()
        try:
            os.remove(self.path)
        except OSError:
            pass
