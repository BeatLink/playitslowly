"""
Play it Slowly

Downloads the audio of a YouTube (or other yt-dlp supported) video so it can be opened like any file.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.
"""

import os
import re
import shutil

from gi.repository import Gio, GLib, Gtk

_ = lambda s: s

YTDLP = "yt-dlp"
PROGRESS = re.compile(r"^\[download\]\s+([0-9.]+)%")


def download_dir():
    """the folder downloads are saved in: Music/YouTube in the user's home"""
    music = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_MUSIC) or os.path.expanduser("~/Music")
    return os.path.join(music, "YouTube")


class Download:
    """one yt-dlp run; calls progress(fraction) while it runs and done(path, error) at the end"""
    def __init__(self, url, progress, done):
        self.progress = progress
        self.done = done
        self.path = None
        self.output = []
        self.cancelled = False
        os.makedirs(download_dir(), exist_ok=True)
        # Opus in its own container needs no re-encoding, and GStreamer and ffmpeg both play it.
        argv = [YTDLP, "--newline", "--progress", "--no-playlist", "--embed-metadata",
                "-f", "bestaudio[acodec=opus]/bestaudio", "-x",
                "-o", os.path.join(download_dir(), "%(title)s [%(id)s].%(ext)s"),
                "--print", "after_move:filepath", url]
        self.process = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        self.stream = Gio.DataInputStream.new(self.process.get_stdout_pipe())
        self.stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)
        self.process.wait_async(None, self.on_exit)

    def on_line(self, stream, result):
        line, _length = stream.read_line_finish_utf8(result)
        if line is None:
            return
        match = PROGRESS.match(line)
        if match:
            self.progress(float(match.group(1)) / 100)
        elif line.startswith("/") and os.path.exists(line):
            self.path = line
        else:
            self.output.append(line)
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, self.on_line)

    def on_exit(self, process, result):
        process.wait_finish(result)
        if self.cancelled:
            return
        if process.get_successful() and self.path:
            self.done(self.path, None)
        else:
            errors = [line for line in self.output if "ERROR" in line] or self.output[-3:]
            self.done(None, "\n".join(errors) or _("yt-dlp failed"))

    def cancel(self):
        self.cancelled = True
        self.process.force_exit()


class YouTubeDialog(Gtk.Dialog):
    """asks for a video URL, downloads its audio and hands the file to opened(uri)"""
    def __init__(self, parent, opened):
        Gtk.Dialog.__init__(self, title=_("Open from YouTube"), transient_for=parent)
        self.opened = opened
        self.download = None
        self.add_button(_("Cancel"), Gtk.ResponseType.CANCEL)
        self.download_button = self.add_button(_("Download"), Gtk.ResponseType.OK)
        self.set_default_response(Gtk.ResponseType.OK)
        box = self.get_content_area()
        box.set_spacing(6)
        box.set_border_width(8)
        label = Gtk.Label(label=_("Paste the address of a video. Its audio is saved in %s.") % download_dir())
        label.set_line_wrap(True)
        label.set_xalign(0.0)
        box.pack_start(label, False, False, 0)
        self.entry = Gtk.Entry()
        self.entry.set_activates_default(True)
        self.entry.set_width_chars(50)
        clipboard = Gtk.Clipboard.get_default(parent.get_display()).wait_for_text()
        if clipboard and clipboard.strip().startswith("http"):
            self.entry.set_text(clipboard.strip())
        box.pack_start(self.entry, False, False, 0)
        self.bar = Gtk.ProgressBar()
        self.bar.set_show_text(True)
        self.bar.set_no_show_all(True)
        box.pack_start(self.bar, False, False, 0)
        self.connect("response", self.on_response)
        self.show_all()

    def on_response(self, dialog, response):
        if response == Gtk.ResponseType.OK:
            url = self.entry.get_text().strip()
            if not url or self.download:
                return
            if not shutil.which(YTDLP):
                self.fail(_("yt-dlp is not installed. Install it to download audio from YouTube."))
                return
            self.download_button.set_sensitive(False)
            self.entry.set_sensitive(False)
            self.bar.show()
            self.bar.set_text(_("Starting..."))
            self.download = Download(url, self.on_progress, self.on_done)
        else:
            if self.download:
                self.download.cancel()
            self.destroy()

    def on_progress(self, fraction):
        self.bar.set_fraction(fraction)
        self.bar.set_text(_("Downloading %d%%") % round(fraction * 100))

    def on_done(self, path, error):
        if error:
            self.fail(error)
            return
        self.destroy()
        self.opened(GLib.filename_to_uri(path, None))

    def fail(self, message):
        self.download = None
        self.download_button.set_sensitive(True)
        self.entry.set_sensitive(True)
        self.bar.hide()
        dialog = Gtk.MessageDialog(transient_for=self, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=_("Could not download the audio"))
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()
