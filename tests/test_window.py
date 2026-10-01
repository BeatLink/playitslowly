"""The main window driven the way a user would: loading, looping, count-in, shortcuts and settings."""

import json
import sys
import time
import types

import pytest

from conftest import key, open_file, position, run_until, uri, wait
from gi.repository import Gtk
from playitslowly import myGtk, youtube


def play_from(win, seconds):
    win.play_button.set_active(True)
    assert run_until(lambda: position(win) is not None)
    win.seek(seconds)
    assert run_until(lambda: abs((position(win) or -99) - seconds) < 0.5), "the seek did not land"


def test_end_position_matches_the_file_after_loading(window, audio):
    """a failed position query right after loading used to leave the end position at 0 (#28)"""
    open_file(window, audio["left"])
    assert abs(window.endchooser.get_adjustment().get_upper() - 6.0) < 0.05
    assert abs(window.endchooser.get_value() - 6.0) < 0.05


def test_title_comes_from_the_tags(window, audio):
    window.set_uri(uri(audio["mp3"]))
    assert run_until(lambda: "Practice Tune" in window.get_title())
    assert window.get_title() == "Test Band - Practice Tune - Play it Slowly"


def test_mp3_without_a_length_header_gets_its_length_while_playing(window, audio):
    """GStreamer only estimates the length of such files once frames flow, so the end position must follow"""
    window.set_uri(uri(audio["mp3"]))
    window.play_button.set_active(True)
    assert run_until(lambda: window.endchooser.get_adjustment().get_upper() > 3.0, 10)
    assert abs(window.endchooser.get_value() - window.endchooser.get_adjustment().get_upper()) < 0.05


def test_waveform_loads_in_the_background(window, audio):
    started = time.monotonic()
    window.set_uri(uri(audio["long"]))
    assert time.monotonic() - started < 1.0, "opening a file must not wait for the waveform"
    assert not window.waveform_loaded
    assert run_until(lambda: window.waveform_loaded, 20)


def test_cancel_in_the_file_dialog_keeps_the_file(window, audio):
    open_file(window, audio["left"])
    run_until(lambda: window.waveform_loaded)
    window.filechanged(None, Gtk.ResponseType.CANCEL)
    assert window.waveform_loaded and window.endchooser.get_adjustment().get_upper() > 5


def test_remote_file_plays_without_a_waveform_and_one_error_dialog(window, monkeypatch):
    # GTK's own file chooser shows a modal error for an unreachable folder, which would stall this loop.
    monkeypatch.setattr(window.filedialog, "set_uri", lambda uri: None)
    monkeypatch.setattr(window.filechooser, "set_uri", lambda uri: None)
    monkeypatch.setattr(window.filedialog, "get_uri", lambda: "http://127.0.0.1:9/missing.mp3")
    window.set_uri("http://127.0.0.1:9/missing.mp3")
    assert window.play_button.get_sensitive() and not window.waveform_loaded
    window.play_button.set_active(True)

    def errors():
        return [w for w in Gtk.Window.list_toplevels() if w.get_title() == "Error" and w.get_visible()]
    assert run_until(lambda: errors(), 10)
    wait(1.0)
    assert len(errors()) == 1, "a broken file should show one error dialog"
    errors()[0].response(Gtk.ResponseType.OK)
    assert run_until(lambda: not errors(), 2), "OK should close the dialog"


def test_loop_restarts_at_the_end_of_the_track_without_a_gap(window, audio):
    open_file(window, audio["left"])
    window.speedchooser.set_value(3.0)
    play_from(window, 3.0)
    samples = []
    run_until(lambda: samples.append(position(window)) or False, 3.0)
    known = [s for s in samples if s is not None]
    assert any(b < a - 3 for a, b in zip(known, known[1:])), "playback should wrap from the end to the start"
    # A silent gapless restart used to hold the position at 0 for about 3 s.
    zeros = max((len(run) for run in "".join("0" if (s or 0) < 0.05 else "1" for s in samples).split("1")), default=0)
    assert zeros * 0.01 < 1.0


def test_without_looping_playback_stops_at_the_end(window, audio):
    open_file(window, audio["left"])
    window.loop_button.set_active(False)
    window.speedchooser.set_value(3.0)
    play_from(window, 4.0)
    assert run_until(lambda: not window.play_button.get_active(), 5)
    assert run_until(lambda: (position(window) or 0) < 0.5, 2)


def test_count_in_waits_before_playing(window, audio):
    open_file(window, audio["left"])
    window.countinchooser.set_value(2)
    window.play_button.set_active(True)
    assert window.play_button.get_label() == "Starting in 2"
    wait(1.2)
    assert window.play_button.get_label() == "Starting in 1"
    assert (position(window) or 0) < 0.1
    assert run_until(lambda: window.play_button.get_label() == "Play", 2)
    assert run_until(lambda: (position(window) or 0) > 0.3, 3)


def test_count_in_before_every_loop(window, audio):
    open_file(window, audio["left"])
    window.countinchooser.set_value(1)
    window.countin_every_loop.set_active(True)
    window.endchooser.set_value(2.0)
    window.speedchooser.set_value(2.0)
    window.play_button.set_active(True)
    assert run_until(lambda: window.play_button.get_label() == "Play", 3)
    assert run_until(lambda: window.play_button.get_label() == "Starting in 1", 4), "the loop restart should count in"
    assert (position(window) or 0) < 0.2


def test_rewind_keys(window, audio):
    open_file(window, audio["long"])
    play_from(window, 20.0)
    before = position(window)
    key(window, "3", ctrl=True, release=True)
    assert run_until(lambda: abs((position(window) or 0) - (before - 3)) < 0.6, 2), "Ctrl+3 rewinds 3 seconds"
    before = position(window)
    key(window, "5")
    assert run_until(lambda: abs((position(window) or 0) - (before - 5)) < 0.6, 2), "5 rewinds 5 seconds"


@pytest.mark.parametrize("name, delta", [("KP_6", 10), ("KP_4", -10), ("KP_9", 15), ("KP_7", -15),
                                         ("KP_3", 5), ("KP_1", -5), ("Right", 5), ("Left", -5),
                                         ("KP_Right", 10)])
def test_number_pad_and_arrows_skip(window, audio, name, delta):
    open_file(window, audio["long"])
    play_from(window, 20.0)
    before = position(window)
    assert key(window, name)
    assert run_until(lambda: abs((position(window) or 0) - (before + delta)) < 0.8, 2)


def test_loop_point_and_playback_keys(window, audio):
    open_file(window, audio["long"])
    play_from(window, 10.0)
    for name, chooser in (("s", window.startchooser), ("e", window.endchooser),
                          ("KP_Divide", window.startchooser), ("KP_Multiply", window.endchooser)):
        key(window, name)
        assert abs(chooser.get_value() - window.positionchooser.get_value()) < 0.01, name
    key(window, "a", ctrl=True)
    assert window.startchooser.get_value() == 0.0
    key(window, "b", ctrl=True)
    assert window.endchooser.get_value() == window.endchooser.get_adjustment().get_upper()
    loop = window.loop_button.get_active()
    key(window, "l")
    assert window.loop_button.get_active() != loop
    key(window, "KP_0")
    assert not window.play_button.get_active()
    key(window, "KP_0")
    assert window.play_button.get_active()
    key(window, "KP_Decimal")
    assert not window.play_button.get_active()


def test_speed_and_pitch_keys(window, audio):
    open_file(window, audio["left"])
    key(window, "KP_8")
    key(window, "KP_Up")  # the same key with Num Lock off
    assert abs(window.speedchooser.get_value() - 1.1) < 1e-6
    key(window, "KP_2")
    assert abs(window.speedchooser.get_value() - 1.05) < 1e-6
    key(window, "KP_5")
    assert window.speedchooser.get_value() == 1.0
    key(window, "KP_Add")
    key(window, "KP_Add")
    key(window, "KP_Subtract")
    assert window.pitchchooser.get_value() == 1.0


def test_single_keys_are_ignored_while_typing(window, audio):
    open_file(window, audio["left"])
    window.set_focus(window.speedchooser.entry)
    loop = window.loop_button.get_active()
    assert not key(window, "l")
    assert window.loop_button.get_active() == loop


def test_nudge_buttons_move_loop_points(window, audio):
    open_file(window, audio["left"])
    window.startchooser.set_value(2.0)
    window.startchooser.nudge_buttons[3].clicked()  # +100 ms
    window.startchooser.nudge_buttons[1].clicked()  # -10 ms
    assert abs(window.startchooser.get_value() - 2.09) < 1e-6


def test_settings_are_remembered_per_file_unless_turned_off(window, audio, tmp_path):
    open_file(window, audio["left"])
    window.speedchooser.set_value(0.8)
    window.balance_mode.set_active_id("midside")
    window.save_config_now()
    saved = json.load(open(tmp_path / "playitslowly.json"))
    entry = saved["files"][uri(audio["left"])]
    assert entry["speed"] == 0.8 and entry["balance_mode"] == "midside"

    window.remember_check.set_active(False)
    window.speedchooser.set_value(1.3)
    window.save_config_now()
    saved = json.load(open(tmp_path / "playitslowly.json"))
    assert saved["remember"] is False
    assert saved["files"][uri(audio["left"])]["speed"] == 0.8, "with remembering off nothing per file is written"


def test_dropped_files_are_opened(window, audio):
    data = types.SimpleNamespace(get_uris=lambda: [uri(audio["left"])])
    window.on_drop(window, None, 0, 0, data, 0, 0)
    assert run_until(lambda: window.endchooser.get_adjustment().get_upper() > 5)


def test_crash_dialog_comes_after_the_traceback(capsys):
    order = []

    class Dialog:
        def __init__(self, *args):
            order.append("dialog")

        def run(self):
            pass

        def destroy(self):
            pass

    saved = sys.excepthook
    sys.excepthook = sys.__excepthook__
    try:
        myGtk.install_exception_hook(dialog=Dialog)
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
            order.insert(0, "printed" if "boom" in capsys.readouterr().err else "missing")
    finally:
        sys.excepthook = saved
    assert order == ["printed", "dialog"]


def test_youtube_prefers_the_installed_module(monkeypatch):
    monkeypatch.setattr(youtube.importlib.util, "find_spec", lambda name: object())
    assert youtube.ytdlp_command() == [sys.executable, "-m", "yt_dlp"]
    monkeypatch.setattr(youtube.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(youtube.shutil, "which", lambda name: "/usr/bin/yt-dlp")
    assert youtube.ytdlp_command() == ["yt-dlp"]
    monkeypatch.setattr(youtube.shutil, "which", lambda name: None)
    assert youtube.ytdlp_command() is None
