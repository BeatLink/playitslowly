#!/usr/bin/env python3
# vim: set fileencoding=utf-8 :
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

import getopt
import mimetypes
import os
import sys
import threading

try:
    import json
except ImportError:
    import simplejson as json

import gi
gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')

from gi.repository import Gtk, GObject, Gst, Gio, Gdk, GLib

Gst.init(None)
GLib.set_prgname("ch.x29a.playitslowly")

from playitslowly.pipeline import Pipeline, BALANCE_MODES, ENCODERS

import logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

# always enable button images

from playitslowly import myGtk
from playitslowly import youtube
myGtk.install()


_ = lambda s: s # may be add gettext later

NAME = "Play it Slowly"
VERSION = "1.6.1"
WEBSITE = "https://github.com/BeatLink/playitslowly"

if sys.platform == "win32":
    CONFIG_PATH = os.path.expanduser("~/playitslowly.json")
else:
    XDG_CONFIG_HOME = os.path.expanduser(os.environ.get("XDG_CONFIG_HOME", "~/.config"))
    if not os.path.exists(XDG_CONFIG_HOME):
        os.mkdir(XDG_CONFIG_HOME)
    CONFIG_PATH = os.path.join(XDG_CONFIG_HOME, "playitslowly.json")

TIME_FORMAT = Gst.Format(Gst.Format.TIME)

# Number pad keys that move the playback position, in seconds.
KEYPAD_SKIP = {"KP_1": -5, "KP_4": -10, "KP_7": -15, "KP_3": 5, "KP_6": 10, "KP_9": 15, "Left": -5, "Right": 5}
# The names the number pad sends with Num Lock off.
KEYPAD_NAVIGATION = {"KP_Insert": "KP_0", "KP_End": "KP_1", "KP_Down": "KP_2", "KP_Next": "KP_3", "KP_Left": "KP_4",
        "KP_Begin": "KP_5", "KP_Right": "KP_6", "KP_Home": "KP_7", "KP_Up": "KP_8", "KP_Prior": "KP_9",
        "KP_Delete": "KP_Decimal"}

def in_pathlist(filename, paths = os.environ.get("PATH").split(os.pathsep)):
    """check if an application is somewhere in $PATH"""
    return any(os.path.exists(os.path.join(path, filename)) for path in paths)

class Config(dict):
    """Very simple json config file"""
    def __init__(self, path=None):
        dict.__init__(self)
        self.path = path

    def load(self):
        with open(self.path, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception as e:
                print("Error loading config: %s", e)
                data = {}
        self.clear()
        self.update(data)

    def save(self):
        with open(self.path, mode="w", encoding="utf-8") as f:
            json.dump(self, f)


class MainWindow(Gtk.Window):
    def __init__(self, sink, config):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)

        self.set_title(NAME)

        try:
            self.set_icon(myGtk.iconfactory.get_icon("ch.x29a.playitslowly", 128))
        except GObject.GError:
            print("could not load playitslowly icon")

        self.set_default_size(600, 200)
        self.set_border_width(5)

        self.vbox = Gtk.VBox()
        self.accel_group = Gtk.AccelGroup()
        self.add_accel_group(self.accel_group)


        self.pipeline = Pipeline(sink)
        self.pipeline.eos = self.on_eos
        self.pipeline.tags = self.on_tags
        self.export = None

        # --- Waveform Drawing Area ---
        self.waveform_area = Gtk.DrawingArea()
        self.waveform_area.set_size_request(600, 100)
        self.waveform_area.connect("draw", self.on_waveform_draw)
        self.waveform_samples = None
        self.waveform_uri = None
        self.waveform_loaded = False
        self.waveform_view_start = 0.0   # fraction of total waveform (0.0–1.0)
        self.waveform_view_end = 1.0     # fraction of total waveform (0.0–1.0)
        self.vbox.pack_start(self.waveform_area, False, False, 4)

        # --- Enable mouse interaction on waveform ---
        self.waveform_area.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.waveform_area.connect("button-press-event", self.on_waveform_click)
        self.waveform_area.connect("button-release-event", self.on_waveform_release)
        self.waveform_area.connect("motion-notify-event", self.on_waveform_motion)

        # Add mouse wheel zoom
        self.waveform_area.add_events(Gdk.EventMask.SCROLL_MASK)
        self.waveform_area.connect("scroll-event", self.on_waveform_scroll)

        # Zoom control button
        self.zoom_button = Gtk.Button(label="Zoom Selection")
        self.zoom_button.connect("clicked", self.on_zoom_selection)
        self.vbox.pack_start(self.zoom_button, False, False, 4)

        # --- Waveform Height Zoom ---
        self.waveform_height_scale = Gtk.Scale.new_with_range(
            Gtk.Orientation.HORIZONTAL, 0.5, 3.0, 0.1
        )
        self.waveform_height_scale.set_value(1.0)
        self.waveform_height_scale.set_digits(1)
        self.waveform_height_scale.connect("value-changed", lambda w: self.waveform_area.queue_draw())
        heightbox = Gtk.HBox()
        heightbox.pack_start(Gtk.Label(label=_("Waveform height")), False, False, 4)
        heightbox.pack_start(self.waveform_height_scale, True, True, 0)
        self.vbox.pack_start(heightbox, False, False, 2)

        self.dragging_marker = None  # "start", "end" or None

        # --- File chooser, speed/pitch/position controls ---        # Connect signals for zooming when start/end sliders move
        self.filedialog = myGtk.FileChooserDialog(None, self, Gtk.FileChooserAction.OPEN)
        self.filedialog.connect("response", self.filechanged)
        self.filedialog.set_local_only(False)
        filechooserhbox = Gtk.HBox()
        self.filechooser = Gtk.FileChooserButton.new_with_dialog(self.filedialog)
        self.filechooser.set_local_only(False)
        filechooserhbox.pack_start(self.filechooser, True, True, 0)
        self.recentbutton = Gtk.Button(label=_("Recent"))
        self.recentbutton.connect("clicked", self.show_recent)
        filechooserhbox.pack_end(self.recentbutton, False, False, 0)
        self.youtubebutton = Gtk.Button(label=_("YouTube"))
        self.youtubebutton.set_tooltip_text(_("Download the audio of a video and open it (Ctrl+Y)"))
        self.youtubebutton.connect("clicked", self.show_youtube)
        filechooserhbox.pack_end(self.youtubebutton, False, False, 0)

        self.speedchooser = myGtk.TextScaleReset(Gtk.Adjustment.new(1.00, 0.10, 4.0, 0.05, 0.05, 0))
        self.speedchooser.scale.connect("value-changed", self.speedchanged)
        self.speedchooser.scale.connect("button-press-event", self.speedpress)
        self.speedchooser.scale.connect("button-release-event", self.speedrelease)
        self.speedchangeing = False

        pitch_adjustment = Gtk.Adjustment.new(0.0, -24.0, 24.0, 1.0, 1.0, 1.0)
        self.pitchchooser = myGtk.TextScaleReset(pitch_adjustment)
        self.pitchchooser.scale.connect("value-changed", self.pitchchanged)

        self.pitchchooser_fine = myGtk.TextScaleReset(Gtk.Adjustment.new(0.0, -50, 50, 1.0, 1.0, 1.0))
        self.pitchchooser_fine.scale.connect("value-changed", self.pitchchanged)

        self.positionchooser = myGtk.ClockScale(Gtk.Adjustment.new(0.0, 0.0, 100.0, 0, 0, 0))
        self.positionchooser.scale.connect("button-press-event", self.start_seeking)
        self.positionchooser.scale.connect("button-release-event", self.positionchanged)
        self.seeking = False

        self.startchooser = myGtk.TextScaleWithCurPos(self.positionchooser, Gtk.Adjustment.new(0.0, 0, 100.0, 0, 0, 0))
        self.startchooser.scale.connect("button-press-event", self.start_seeking)
        self.startchooser.scale.connect("button-release-event", self.seeked)
        self.startchooser.add_accelerator("clicked", self.accel_group, ord('['), Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        self.startchooser.add_accelerator("clicked", self.accel_group, ord('['), 0, Gtk.AccelFlags.VISIBLE)

        self.endchooser = myGtk.TextScaleWithCurPos(self.positionchooser, Gtk.Adjustment.new(1.0, 0, 100.0, 0.01, 0.01, 0))
        self.endchooser.scale.connect("button-press-event", self.start_seeking)
        self.endchooser.scale.connect("button-release-event", self.seeked)
        self.endchooser.add_accelerator("clicked", self.accel_group, ord(']'), Gdk.ModifierType.CONTROL_MASK, Gtk.AccelFlags.VISIBLE)
        self.endchooser.add_accelerator("clicked", self.accel_group, ord(']'), 0, Gtk.AccelFlags.VISIBLE)
        for button in self.startchooser.nudge_buttons + self.endchooser.nudge_buttons:
            button.connect("clicked", lambda sender: self.save_config())
        self.startchooser.scale.connect("value-changed", self.on_selection_changed)
        self.endchooser.scale.connect("value-changed", self.on_selection_changed)

        self.vbox.pack_start(filechooserhbox, False, False, 0)
        self.vbox.pack_start(self.positionchooser, True, True, 0)
        self.vbox.pack_start(myGtk.form([
            ("Speed (times)", self.speedchooser),
            ("Pitch (semitones)", self.pitchchooser),
            ("Fine Pitch (cents)", self.pitchchooser_fine),
            ("Start Position (seconds)", self.startchooser),
            ("End Position (seconds)", self.endchooser)
        ]), False, False, 0)

        # --- Options: balance, count-in, limiter, per-file memory ---
        self.balance_mode = Gtk.ComboBoxText()
        for key, label in BALANCE_MODES:
            self.balance_mode.append(key, label)
        self.balance_mode.set_active_id("stereo")
        self.balance_mode.connect("changed", self.balancechanged)
        self.balancechooser = myGtk.TextScaleReset(Gtk.Adjustment.new(0.0, -1.0, 1.0, 0.05, 0.05, 0))
        self.balancechooser.scale.connect("value-changed", self.balancechanged)
        self.balancechooser.set_sensitive(False)
        balancebox = Gtk.HBox()
        balancebox.pack_start(self.balance_mode, False, False, 4)
        balancebox.pack_start(self.balancechooser, True, True, 0)

        self.countin_id = None
        self.countinchooser = myGtk.TextScaleReset(Gtk.Adjustment.new(0.0, 0.0, 10.0, 1.0, 1.0, 0))
        self.countinchooser.scale.connect("value-changed", self.optionschanged)
        self.countin_every_loop = Gtk.CheckButton(label=_("Before every loop"))
        self.countin_every_loop.connect("toggled", self.optionschanged)
        countinbox = Gtk.HBox()
        countinbox.pack_start(self.countinchooser, True, True, 0)
        countinbox.pack_start(self.countin_every_loop, False, False, 4)

        self.limiter_check = Gtk.CheckButton(label=_("Limiter (prevents clipping)"))
        self.limiter_check.connect("toggled", self.optionschanged)
        self.remember_check = Gtk.CheckButton(label=_("Remember settings for each file"))
        self.remember_check.connect("toggled", self.optionschanged)
        checkbox = Gtk.HBox()
        checkbox.pack_start(self.limiter_check, False, False, 4)
        checkbox.pack_start(self.remember_check, False, False, 4)

        options = Gtk.Expander(label=_("Options"))
        options.add(myGtk.form([
            (_("Balance"), balancebox),
            (_("Count-in (seconds)"), countinbox),
            ("", checkbox),
        ]))
        self.vbox.pack_start(options, False, False, 0)

        buttonbox = Gtk.HButtonBox()
        myGtk.add_style_class(buttonbox, 'buttonBox')
        self.vbox.pack_end(buttonbox, False, False, 0)

        self.play_button = Gtk.ToggleButton(label='Play')
        self.play_button.connect("toggled", self.play)

        self.play_button.set_sensitive(False)
        buttonbox.pack_start(self.play_button, True, True, 0)
        self.play_button.add_accelerator("clicked", self.accel_group, ord(' '), 0, Gtk.AccelFlags.VISIBLE)

        self.back_button = Gtk.Button.new_with_mnemonic('Rewind')
        self.back_button.connect("clicked", self.back)
        #self.back_button.set_use_stock(True)
        self.back_button.set_sensitive(False)
        buttonbox.pack_start(self.back_button, True, True, 0)

        self.loop_button = Gtk.ToggleButton(label=_("Loop"))
        self.loop_button.set_tooltip_text(_("Repeat between the start and end positions (L)"))
        self.loop_button.connect("toggled", self.optionschanged)
        buttonbox.pack_start(self.loop_button, True, True, 0)

        self.volume_button = Gtk.VolumeButton()
        self.volume_button.set_value(1.0)
        self.volume_button.set_relief(Gtk.ReliefStyle.NORMAL)
        self.volume_button.connect("value-changed", self.volumechanged)
        buttonbox.pack_start(self.volume_button, True, True, 0)

        self.save_as_button = Gtk.Button.new_with_mnemonic('Save As')
        self.save_as_button.connect("clicked", self.save)
        self.save_as_button.set_sensitive(False)
        buttonbox.pack_start(self.save_as_button, True, True, 0)

        button_about = Gtk.Button.new_with_mnemonic("About")
        button_about.connect("clicked", self.about)
        buttonbox.pack_end(button_about, True, True, 0)

        self.connect("key-release-event", self.key_release)
        self.connect("key-press-event", self.key_press)

        # Audio files dropped from a file manager are opened.
        self.drag_dest_set(Gtk.DestDefaults.ALL, [], Gdk.DragAction.COPY)
        self.drag_dest_add_uri_targets()
        self.connect("drag-data-received", self.on_drop)

        self.add(self.vbox)
        self.connect("destroy", Gtk.main_quit)

        self.config = config
        self.config_saving = False
        self.load_config()

        GLib.timeout_add(50, self.refresh_waveform)

    def refresh_waveform(self):
        """repaint the waveform while the playback line is moving"""
        if self.waveform_loaded and self.play_button.get_active() and self.waveform_area.get_mapped():
            self.waveform_area.queue_draw()
        return True

    # ------------------------------------------------------------
    # Waveform mouse interaction
    # ------------------------------------------------------------
    def on_waveform_click(self, widget, event):
        if not self.waveform_loaded:
            return False
        width = widget.get_allocation().width
        total = self.endchooser.get_adjustment().get_upper()
        if total <= 0:
            return False

        # Convert time fraction to pixel X positions
        start_frac = self.startchooser.get_value() / total
        end_frac = self.endchooser.get_value() / total

        def frac_to_x(f):
            return (f - self.waveform_view_start) / (
                self.waveform_view_end - self.waveform_view_start
            ) * width

        x1 = frac_to_x(start_frac)
        x2 = frac_to_x(end_frac)

        # Detect click proximity (within 5 px)
        if abs(event.x - x1) < 5:
            self.dragging_marker = "start"
        elif abs(event.x - x2) < 5:
            self.dragging_marker = "end"
        else:
            self.dragging_marker = None
        return True

    def on_waveform_motion(self, widget, event):
        if not self.dragging_marker or not self.waveform_loaded:
            return False

        width = widget.get_allocation().width
        total = self.endchooser.get_adjustment().get_upper()
        frac = event.x / max(1, width)
        abs_frac = self.waveform_view_start + frac * (
            self.waveform_view_end - self.waveform_view_start
        )
        new_time = abs_frac * total

        if self.dragging_marker == "start":
            new_time = max(0.0, min(new_time, self.endchooser.get_value() - 0.01))
            self.startchooser.set_value(new_time)
        elif self.dragging_marker == "end":
            new_time = min(total, max(new_time, self.startchooser.get_value() + 0.01))
            self.endchooser.set_value(new_time)

        self.on_selection_changed(None)
        return True

    def on_waveform_release(self, widget, event):
        self.dragging_marker = None
        return True

    def on_waveform_scroll(self, widget, event):
        """Zoom in/out centered on cursor position."""
        if not self.waveform_loaded:
            return False

        zoom_factor = 0.8 if event.direction == Gdk.ScrollDirection.UP else 1.25

        # Cursor fraction within the widget
        width = widget.get_allocation().width
        cursor_frac = event.x / max(1, width)

        total_len = 1.0
        view_center = self.waveform_view_start + cursor_frac * (self.waveform_view_end - self.waveform_view_start)
        current_width = self.waveform_view_end - self.waveform_view_start
        new_width = min(1.0, max(0.0001, current_width * zoom_factor))

        self.waveform_view_start = max(0.0, view_center - new_width / 2.0)
        self.waveform_view_end = min(1.0, self.waveform_view_start + new_width)

        # Adjust if we go out of range
        if self.waveform_view_end > 1.0:
            shift = self.waveform_view_end - 1.0
            self.waveform_view_start -= shift
            self.waveform_view_end = 1.0
        if self.waveform_view_start < 0.0:
            self.waveform_view_end -= self.waveform_view_start
            self.waveform_view_start = 0.0

        self.waveform_area.queue_draw()
        return True

    def on_zoom_selection(self, button):
        """Zoom so selection fits roughly from 10% to 90% of width."""
        total = self.endchooser.get_adjustment().get_upper()
        if total <= 0:
            return

        sel_start = self.startchooser.get_value() / total
        sel_end = self.endchooser.get_value() / total
        sel_width = max(0.0001, sel_end - sel_start)

        # Compute zoomed region to place selection 10%-90% of view
        view_width = sel_width / 0.8
        view_center = (sel_start + sel_end) / 2.0

        self.waveform_view_start = max(0.0, view_center - view_width / 2.0)
        self.waveform_view_end = min(1.0, self.waveform_view_start + view_width)

        if self.waveform_view_end > 1.0:
            shift = self.waveform_view_end - 1.0
            self.waveform_view_start -= shift
            self.waveform_view_end = 1.0
        if self.waveform_view_start < 0.0:
            self.waveform_view_end -= self.waveform_view_start
            self.waveform_view_start = 0.0

        self.waveform_area.queue_draw()

    def on_waveform_draw(self, widget, cr):
        import cairo
        if not self.waveform_loaded or self.waveform_samples is None:
            return False

        alloc = widget.get_allocation()
        width, height = alloc.width, alloc.height
        samples = self.waveform_samples
        if len(samples) == 0:
            return False

        max_val = max(abs(samples.max()), abs(samples.min()))
        if max_val == 0:
            return False

        import numpy as np
        norm_samples = samples / max_val

        # --- Compute zoomed region indices ---
        total_len = len(norm_samples)
        view_start_idx = int(self.waveform_view_start * total_len)
        view_end_idx = int(self.waveform_view_end * total_len)
        view_end_idx = min(view_end_idx, total_len - 1)

        # --- Slice zoom region ---
        visible = norm_samples[view_start_idx:view_end_idx]
        if len(visible) < 2:
            return False

        # --- Resample to match widget width ---
        # This keeps the zoomed region filling the entire view width
        x = np.linspace(0, len(visible) - 1, width)
        points = np.interp(x, np.arange(len(visible)), visible)

        mid = height // 2
        vertical_zoom = self.waveform_height_scale.get_value() if hasattr(self, "waveform_height_scale") else 1.0

        # Apply vertical zoom (clamp so it doesn't overflow)
        amp = int((height // 2 - 2) * vertical_zoom)

        # Fill background to make waveform visible
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        cr.set_source_rgb(0.1, 0.1, 0.1)
        cr.rectangle(0, 0, width, height)
        cr.fill()

        # Draw waveform
        cr.set_source_rgb(0.2, 0.6, 1.0)
        cr.set_line_width(1)
        cr.move_to(0, mid)
        for x, y in enumerate(points):
            cr.line_to(x, mid - int(y * amp))
        cr.stroke()

        # --- Draw selection area ---
        total = self.endchooser.get_adjustment().get_upper()
        if total > 0:
            start_frac = self.startchooser.get_value() / total
            end_frac = self.endchooser.get_value() / total

            # Map absolute fractions to local visible window
            def frac_to_x(f):
                return (f - self.waveform_view_start) / (self.waveform_view_end - self.waveform_view_start) * width

            x1 = frac_to_x(start_frac)
            x2 = frac_to_x(end_frac)

            # --- Selection (loop region) overlay ---
            cr.set_source_rgba(0.9, 0.3, 0.4, 0.25)  # translucent pink/red
            cr.rectangle(min(x1, x2), 0, abs(x2 - x1), height)
            cr.fill()

            try:
                # Robust position/duration query from GStreamer
                ok_pos, pos_ns = self.pipeline.playbin.query_position(Gst.Format.TIME)
                ok_dur, dur_ns = self.pipeline.playbin.query_duration(Gst.Format.TIME)

                if not ok_pos:
                    pos_ns = 0
                if not ok_dur or dur_ns == 0:
                    # fall back to endchooser upper bound if duration not known yet
                    dur_ns = int(self.endchooser.get_adjustment().get_upper() * Gst.SECOND)

                # Convert to seconds
                pos_time = pos_ns / Gst.SECOND
                dur_time = dur_ns / Gst.SECOND
                total_time = max(dur_time, 0.001)

                pos_frac = min(1.0, max(0.0, pos_time / total_time))
                logging.debug(f"Playback line: {pos_time:.2f}s / {total_time:.2f}s -> {pos_frac:.2%}")
            except Exception as e:
                logging.debug(f"Waveform position query failed: {e}")
                pos_frac = 0.0

            x_pos = frac_to_x(pos_frac)

            # draw blue overlay for played region
            if x_pos > 0:
                cr.set_source_rgba(0.3, 0.6, 1.0, 0.25)
                cr.rectangle(0, 0, min(x_pos, width), height)
                cr.fill()

                # --- Moving playback line ---
                cr.set_source_rgb(1.0, 1.0, 1.0)  # white line
                cr.set_line_width(1.0)
                if 0 <= x_pos <= width:
                    cr.move_to(x_pos, 0)
                    cr.line_to(x_pos, height)
                    cr.stroke()

                # optional small circle marker at mid height
                cr.arc(x_pos, mid, 2.0, 0, 2 * np.pi)
                cr.fill()

            # --- Start/End marker lines (contrasting color) ---
            cr.set_source_rgb(1.0, 0.6, 0.0)  # bright orange markers
            cr.set_line_width(1.2)
            for xline in (x1, x2):
                if 0 <= xline <= width:
                    cr.move_to(xline, 0)
                    cr.line_to(xline, height)
            cr.stroke()

        return False


    def on_selection_changed(self, sender):
        """Update waveform zoom when start or end slider moves."""
        try:
            total = self.endchooser.get_adjustment().get_upper()
            start = self.startchooser.get_value()
            end = self.endchooser.get_value()
            if end <= start or total <= 0:
                return

            # Convert start/end to fractional range
            sel_start = start / total
            sel_end = end / total

            # Center waveform view on selection, keeping it ~80% of window
            sel_center = (sel_start + sel_end) / 2.0
            sel_width = max(0.0001, sel_end - sel_start)

            view_width = min(1.0, sel_width / 0.8)
            view_start = max(0.0, sel_center - view_width / 2.0)
            view_end = min(1.0, view_start + view_width)

            # Adjust if we hit end boundary
            if view_end > 1.0:
                shift = view_end - 1.0
                view_start = max(0.0, view_start - shift)
                view_end = 1.0

            self.waveform_view_start = view_start
            self.waveform_view_end = view_end

            self.waveform_area.queue_draw()
        except Exception as e:
            print(f"[ERROR] on_selection_changed: {e}")


    def load_waveform(self, uri):
        """decode the waveform in a background thread so the window stays responsive"""
        self.waveform_uri = uri
        self.waveform_samples = None
        self.waveform_loaded = False
        self.waveform_view_start = 0.0
        self.waveform_view_end = 1.0
        self.waveform_area.queue_draw()
        path = Gio.File.new_for_uri(uri).get_path() if uri else None
        if not path:
            # Remote files still play but get no waveform, since a stream may never end.
            return
        threading.Thread(target=self.extract_waveform, args=(uri, path), daemon=True).start()

    def extract_waveform(self, uri, path):
        try:
            from playitslowly.waveform import WaveformExtractor
            samples = WaveformExtractor(uri).get_samples(50000)
        except Exception as e:
            logging.error(f"Waveform load error: {e}")
            return
        GLib.idle_add(self.waveform_ready, uri, samples)

    def waveform_ready(self, uri, samples):
        # Ignore a result that arrives after the user has opened another file.
        if uri == self.waveform_uri:
            self.waveform_samples = samples
            self.waveform_loaded = True
            self.waveform_area.queue_draw()
        return False

    def speedpress(self, *args):
        self.speedchangeing = True

    def speedrelease(self, *args):
        self.speedchangeing = False
        self.speedchanged()

    def get_pitch(self):
        return self.pitchchooser.get_value()+self.pitchchooser_fine.get_value()*0.01

    def set_pitch(self, value):
        semitones = round(value)
        cents = round((value-semitones)*100)
        self.pitchchooser.set_value(semitones)
        self.pitchchooser_fine.set_value(cents)

    def add_recent(self, uri):
        manager = Gtk.RecentManager.get_default()
        app_exec = "playitslowly \"%s\"" % uri
        mime_type, certain = Gio.content_type_guess(uri)
        if mime_type:
            recent_data = Gtk.RecentData()
            recent_data.app_name = "playitslowly"
            recent_data.app_exec = "playitslowly"
            recent_data.mime_type = mime_type
            manager.add_full(uri, recent_data)
            logging.debug(f"Added to recents: {uri} ({mime_type})")


    def show_recent(self, sender=None):
        dialog = Gtk.RecentChooserDialog(_("Recent Files"), self, None,
                (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                 Gtk.STOCK_OPEN, Gtk.ResponseType.OK))

        filter = Gtk.RecentFilter()
        filter.set_name("playitslowly")
        filter.add_application("playitslowly")
        dialog.add_filter(filter)

        filter2 = Gtk.RecentFilter()
        filter2.set_name(_("All"))
        filter2.add_mime_type("audio/*")
        dialog.add_filter(filter2)

        dialog.set_local_only(False)

        dialog.set_filter(filter)

        if dialog.run() == Gtk.ResponseType.OK and dialog.get_current_item():
            uri = dialog.get_current_item().get_uri()
            if isinstance(uri, bytes):
                uri = uri.decode('utf-8')
            self.set_uri(uri)
        dialog.destroy()

    def set_uri(self, uri):
        logging.info(f"Opening: {uri}")
        self.filedialog.set_uri(uri)
        self.filechooser.set_uri(uri)
        self.filechanged(uri=uri)

    def load_config(self):
        self.config_saving = True # do not save while loading
        self.loop_button.set_active(self.config.get("loop", True))
        self.countinchooser.set_value(self.config.get("countin", 0))
        self.countin_every_loop.set_active(self.config.get("countin_every_loop", False))
        self.limiter_check.set_active(self.config.get("limiter", True))
        self.remember_check.set_active(self.config.get("remember", True))
        self.pipeline.set_limiter(self.limiter_check.get_active())
        lastfile = self.config.get("lastfile")
        if lastfile:
            self.set_uri(lastfile)
        self.config_saving = False

    def reset_settings(self):
        self.speedchooser.set_value(1.0)
        self.speedchanged()
        self.set_pitch(0.0)
        self.startchooser.get_adjustment().set_property("upper", 0.0)
        self.startchooser.set_value(0.0)
        self.endchooser.get_adjustment().set_property("upper", 1.0)
        self.endchooser.set_value(1.0)
        self.balance_mode.set_active_id("stereo")
        self.balancechooser.set_value(0.0)

    def optionschanged(self, sender=None):
        self.pipeline.set_limiter(self.limiter_check.get_active())
        self.save_config()

    def balancechanged(self, sender=None):
        mode = self.balance_mode.get_active_id() or "stereo"
        self.balancechooser.set_sensitive(mode != "stereo")
        self.pipeline.set_balance(mode, self.balancechooser.get_value())
        self.save_config()

    def load_file_settings(self, filename):
        logging.debug(f"Loading file settings for: {filename}")
        self.add_recent(filename)
        self.load_waveform(filename)
        if not self.remember_check.get_active() or filename not in self.config.get("files", {}):
            self.reset_settings()
            self.pipeline.set_file(filename)
            self.pipeline.pause()
            from gi.repository import GLib
            GLib.timeout_add(100, self.update_position)
            return
        settings = self.config["files"][filename]
        self.speedchooser.set_value(settings["speed"])
        self.set_pitch(settings["pitch"])
        self.startchooser.get_adjustment().set_property("upper", settings["duration"])
        self.startchooser.set_value(settings["start"])
        self.endchooser.get_adjustment().set_property("upper", settings["duration"] or 1.0)
        self.endchooser.set_value(settings["end"])
        self.volume_button.set_value(settings["volume"])
        self.balance_mode.set_active_id(settings.get("balance_mode", "stereo"))
        self.balancechooser.set_value(settings.get("balance", 0.0))

    def save_config(self):
        """saves the config file with a delay"""
        if self.config_saving:
            return
        from gi.repository import GLib
        GLib.timeout_add(1000, self.save_config_now)
        self.config_saving = True

    def save_config_now(self):
        self.config_saving = False
        lastfile = self.filedialog.get_uri()
        self.config["lastfile"] = lastfile
        self.config["loop"] = self.loop_button.get_active()
        self.config["countin"] = self.countinchooser.get_value()
        self.config["countin_every_loop"] = self.countin_every_loop.get_active()
        self.config["limiter"] = self.limiter_check.get_active()
        self.config["remember"] = self.remember_check.get_active()
        if not lastfile or not self.remember_check.get_active():
            self.config.save()
            return False
        settings = {}
        settings["speed"] = self.speedchooser.get_value()
        settings["pitch"] = self.get_pitch()
        settings["duration"] = self.startchooser.get_adjustment().get_property("upper")
        settings["start"] = self.startchooser.get_value()
        settings["end"] = self.endchooser.get_value()
        settings["volume"] = self.volume_button.get_value()
        settings["balance_mode"] = self.balance_mode.get_active_id()
        settings["balance"] = self.balancechooser.get_value()
        self.config.setdefault("files", {})[lastfile] = settings

        self.config.save()

    def key_release(self, sender, event):
        if not event.state & Gdk.ModifierType.CONTROL_MASK:
            return
        try:
            val = int(chr(event.keyval))
        except ValueError:
            return
        self.back(self, val)

    def key_press(self, sender, event):
        """keyboard shortcuts; the single keys are ignored while typing in a text field"""
        key = Gdk.keyval_name(event.keyval) or ""
        if event.state & Gdk.ModifierType.CONTROL_MASK:
            return self.control_shortcut(key.lower())
        if event.state & Gdk.ModifierType.MOD1_MASK or isinstance(self.get_focus(), Gtk.Entry):
            return False
        # With Num Lock off the keypad sends its navigation names, so map those to the digits too.
        key = KEYPAD_NAVIGATION.get(key, key)
        if key in ("s", "a", "KP_Divide"):
            self.startchooser.update_to_current_position()
            self.save_config()
        elif key in ("e", "b", "KP_Multiply"):
            self.endchooser.update_to_current_position()
            self.save_config()
        elif key == "l":
            self.loop_button.set_active(not self.loop_button.get_active())
        elif key == "0":
            self.seek(self.startchooser.get_value())
        elif key in ("1", "2", "3", "4", "5", "6", "7", "8", "9"):
            self.back(None, int(key))
        elif key in KEYPAD_SKIP:
            self.skip(KEYPAD_SKIP[key])
        elif key in ("KP_2", "KP_8"):
            self.speedchooser.set_value(self.speedchooser.get_value() + (0.05 if key == "KP_8" else -0.05))
        elif key == "KP_5":
            self.speedchooser.set_value(1.0)
        elif key in ("KP_Add", "KP_Subtract"):
            self.pitchchooser.set_value(self.pitchchooser.get_value() + (1 if key == "KP_Add" else -1))
        elif key == "KP_0":
            self.play_button.set_active(not self.play_button.get_active())
        elif key == "KP_Decimal":
            self.play_button.set_active(False)
            self.rewind_to_start()
        elif key == "Home":
            self.rewind_to_start()
        else:
            return False
        return True

    def control_shortcut(self, key):
        if key == "o":
            # The dialog's response handler opens the chosen file.
            self.filedialog.run()
            self.filedialog.hide()
        elif key == "r":
            self.show_recent()
        elif key == "y":
            self.show_youtube()
        elif key == "q":
            self.destroy()
        elif key == "a":
            self.startchooser.set_value(0.0)
            self.save_config()
        elif key == "b":
            self.endchooser.set_value(self.endchooser.get_adjustment().get_upper())
            self.save_config()
        else:
            return False
        return True

    def rewind_to_start(self):
        """go to the loop start while looping, otherwise to the start of the song"""
        self.seek(self.startchooser.get_value() if self.loop_button.get_active() else 0.0)

    def skip(self, seconds):
        """move the playback position by seconds, forward or back, staying inside the song"""
        ok_position, position = self.pipeline.playbin.query_position(TIME_FORMAT)
        ok_duration, duration = self.pipeline.playbin.query_duration(TIME_FORMAT)
        if not (ok_position and ok_duration):
            return
        target = self.pipeline.song_time(position) + seconds
        self.seek(max(0.0, min(target, self.pipeline.song_time(duration) - 0.1)))

    def on_drop(self, widget, context, x, y, data, info, time):
        uris = data.get_uris()
        if uris:
            self.set_uri(uris[0])

    def show_youtube(self, sender=None):
        youtube.YouTubeDialog(self, self.set_uri)

    def on_tags(self, taglist):
        """show the song's artist and title from its tags in the window title"""
        ok_title, title = taglist.get_string("title")
        if not ok_title:
            return
        ok_artist, artist = taglist.get_string("artist")
        self.set_title("%s - %s" % ("%s - %s" % (artist, title) if ok_artist else title, NAME))

    def volumechanged(self, sender, foo):
        self.pipeline.set_volume(sender.get_value())
        self.save_config()

    def save(self, sender):
        if self.export:
            # While exporting, the button cancels the export instead.
            self.export.cancel()
            self.export_done(None, None)
            return
        source = self.filedialog.get_uri()
        dialog = myGtk.FileChooserDialog(_("Save modified version as (.wav, .mp3, .ogg or .flac)"),
                self, Gtk.FileChooserAction.SAVE)
        dialog.set_do_overwrite_confirmation(True)
        name = os.path.splitext(Gio.File.new_for_uri(source).get_basename() or "export")[0]
        dialog.set_current_name("%s-%gx.wav" % (name, self.speedchooser.get_value()))
        section_check = Gtk.CheckButton(label=_("Only the section between the start and end positions"))
        section_check.set_active(self.loop_button.get_active())
        dialog.set_extra_widget(section_check)
        if dialog.run() == Gtk.ResponseType.OK:
            path = dialog.get_filename()
            if os.path.splitext(path)[1].lower() not in ENCODERS:
                path += ".wav"
            section = (self.startchooser.get_value(), self.endchooser.get_value()) if section_check.get_active() else None
            self.export = self.pipeline.save_file(source, path, lambda error: self.export_done(path, error), section)
            GLib.timeout_add(250, self.export_progress)
            self.export_progress()
        dialog.destroy()

    def export_progress(self):
        if not self.export:
            return False
        self.save_as_button.set_label(_("Cancel saving (%d%%)") % round(self.export.progress() * 100))
        return True

    def export_done(self, path, error):
        self.export = None
        self.save_as_button.set_label(_("Save As"))
        if error:
            myGtk.show_error(_("Could not save %s: %s") % (path, error))

    def filechanged(self, sender=None, response_id=Gtk.ResponseType.OK, uri=None):
        if response_id != Gtk.ResponseType.OK:
            return

        self.play_button.set_sensitive(True)
        self.back_button.set_sensitive(True)
        self.save_as_button.set_sensitive(True)
        self.play_button.set_active(False)
        self.set_title(NAME)

        self.pipeline.reset()
        self.seek(0)
        self.save_config()

        if uri:
            self.load_file_settings(uri)
        else:
            from gi.repository import GLib
            GLib.timeout_add(1, lambda: self.load_file_settings(self.filedialog.get_uri()))

    def start_seeking(self, sender, foo):
        self.seeking = True

    def seeked(self, sender, foo):
        self.seeking = False
        self.save_config()

    def positionchanged(self, sender, foo):
        self.seek(sender.get_value())
        self.seeking = False
        self.save_config()

    def seek(self, pos=0):
        if self.positionchooser.get_value() != pos:
            self.positionchooser.set_value(pos)
        pos = self.pipeline.pipe_time(pos)
        self.pipeline.playbin.seek_simple(TIME_FORMAT, Gst.SeekFlags.FLUSH, pos or 0)
        self.waveform_area.queue_draw()

    def speedchanged(self, *args):
        if self.speedchangeing:
            return
        pos = self.positionchooser.get_value()
        self.pipeline.set_speed(self.speedchooser.get_value())
        # hack to get gstreamer to calculate the position again
        self.seek(pos)
        self.save_config()

    def pitchchanged(self, sender):
        self.pipeline.set_pitch(2**(self.get_pitch()/12.0))
        self.save_config()

    def back(self, sender, amount=None):
        ok, position = self.pipeline.playbin.query_position(TIME_FORMAT)
        if not ok:
            return
        if amount:
            t = self.pipeline.song_time(position)-amount
            if t < 0:
                t = 0
        else:
            t = self.startchooser.get_value()
        self.seek(t)

    def on_eos(self):
        """loop back to the start position, or stop there when looping is off"""
        if not self.play_button.get_active():
            return
        if self.loop_button.get_active():
            self.restart_loop()
        else:
            self.play_button.set_active(False)
            self.seek(self.startchooser.get_value())

    def restart_loop(self):
        """jump back to the start position, waiting for the count-in first when it is set for every loop"""
        countin = self.countin_every_loop.get_active() and self.countinchooser.get_value() > 0
        if countin:
            self.pipeline.pause()
        self.seek(self.startchooser.get_value() + 0.01)
        if countin:
            self.start_countin()

    def start_countin(self):
        """wait the count-in time before playing, showing the seconds left on the play button"""
        self.cancel_countin()
        self.countin_left = int(self.countinchooser.get_value())
        self.play_button.set_label(_("Starting in %d") % self.countin_left)
        self.countin_id = GLib.timeout_add(1000, self.countin_tick)

    def countin_tick(self):
        self.countin_left -= 1
        if self.countin_left > 0:
            self.play_button.set_label(_("Starting in %d") % self.countin_left)
            return True
        self.countin_id = None
        self.play_button.set_label(_("Play"))
        self.pipeline.play()
        return False

    def cancel_countin(self):
        if self.countin_id:
            GLib.source_remove(self.countin_id)
            self.countin_id = None
            self.play_button.set_label(_("Play"))

    def play(self, sender):
        if sender.get_active():
            uri = self.filedialog.get_uri()
            # Re-setting the same uri queues it as the next gapless track, which hides the end of the stream.
            if self.pipeline.playbin.get_property("current-uri") != uri:
                self.pipeline.set_file(uri)
            if self.countinchooser.get_value() > 0:
                self.pipeline.pause()
                self.start_countin()
            else:
                self.pipeline.play()
            GObject.timeout_add(100, self.update_position)
        else:
            self.cancel_countin()
            self.pipeline.pause()

    def update_position(self):
        """update the position of the scales and pipeline"""
        if self.seeking:
            return self.play_button.get_active()

        ok_position, position = self.pipeline.playbin.query_position(TIME_FORMAT)
        ok_duration, duration = self.pipeline.playbin.query_duration(TIME_FORMAT)
        # Queries fail for a moment after a file loads, so keep polling until they succeed.
        if not (ok_position and ok_duration) or duration <= 0:
            return True
        position = self.pipeline.song_time(position)
        duration = self.pipeline.song_time(duration)

        if duration is None or duration <= 0:
            return self.play_button.get_active()

        if self.positionchooser.get_adjustment().get_property("upper") != duration:
            self.positionchooser.set_range(0.0, max(0.001, duration))
            self.save_config()

        end_adjustment = self.endchooser.get_adjustment()
        delta = end_adjustment.get_value() - end_adjustment.get_upper()

        if delta <= -duration:
            delta = 0

        self.startchooser.set_range(0.0, duration)
        self.endchooser.set_range(0.0, duration)
        self.endchooser.set_value(duration+delta)

        self.positionchooser.set_value(position)
        self.positionchooser.queue_draw()

        start = self.startchooser.get_value()
        end = self.endchooser.get_value()

        # The start and end positions only bound playback while looping, and not during a count-in.
        if not self.loop_button.get_active() or self.countin_id:
            return self.play_button.get_active()

        if end <= start:
            self.play_button.set_active(False)
            return False

        if position >= end or position < start:
            self.restart_loop()
            return True

        return self.play_button.get_active()

    def about(self, sender):
        """show an about dialog"""
        about = Gtk.AboutDialog()
        about.set_transient_for(self)
        about.set_logo(myGtk.iconfactory.get_icon("ch.x29a.playitslowly", 128))
        about.set_name(NAME)
        about.set_program_name(NAME)
        about.set_version(VERSION)
        about.set_authors(["Jonas Wagner", "Elias Dorneles"])
        about.set_translator_credits(_("translator-credits"))
        about.set_copyright("Copyright (c) 2009 - 2015 Jonas Wagner")
        about.set_website(WEBSITE)
        about.set_website_label(WEBSITE)
        about.set_license("""
Copyright (C) 2009 - 2015 Jonas Wagner
This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.
""")
        about.run()
        about.destroy()

css = b"""
.buttonBox GtkButton GtkLabel { padding-left: 4px; }
"""





def main():
    sink = "autoaudiosink"
    if in_pathlist("gstreamer-properties"):
        sink = "gconfaudiosink"
    options, arguments = getopt.getopt(sys.argv[1:], "h", ["help", "sink="])
    for option, argument in options:
        if option in ("-h", "--help"):
            print("Usage: playitslowly [OPTIONS]... [FILE]")
            print("Options:")
            print('--sink=sink      specify gstreamer sink for playback')
            sys.exit()
        elif option == "--sink":
            print("sink", argument)
            sink = argument
    config = Config(CONFIG_PATH)
    try:
        config.load()
    except IOError:
        pass

    style_provider = Gtk.CssProvider()

    style_provider.load_from_data(css)

    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        style_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )

    win = MainWindow(sink, config)

    if arguments:
        uri = arguments[0]
        if not uri.startswith("file://"):
            uri = "file://" + os.path.abspath(uri)
        win.set_uri(uri)
    win.show_all()
    Gtk.main()

if __name__ == "__main__":
    main()
