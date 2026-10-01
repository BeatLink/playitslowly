"""The audio side: balance matrices, the effects chain, exports and the waveform decoder."""

import os

import pytest

from conftest import decode, discover, peak_db, run_until, uri
from gi.repository import Gst
from playitslowly import pipeline as pl
from playitslowly.waveform import WaveformExtractor

LOUD = -20  # the left-only test tone peaks at about -12 dBFS
SILENT = -60


@pytest.mark.parametrize("mode", [key for key, label in pl.BALANCE_MODES])
def test_centre_of_every_balance_mode_leaves_stereo_alone(mode):
    assert pl.balance_matrix(mode, 0.0) == [[1.0, 0.0], [0.0, 1.0]]


@pytest.mark.parametrize("mode, value, expected", [
    ("midside", -1, [[0.5, 0.5], [0.5, 0.5]]),
    ("midside", 1, [[0.5, -0.5], [-0.5, 0.5]]),
    ("balance", -1, [[1.0, 0.0], [1.0, 0.0]]),
    ("balance", 1, [[0.0, 1.0], [0.0, 1.0]]),
    ("leftright", -1, [[1.0, 0.0], [0.0, 0.0]]),
    ("leftright", 0.5, [[0.5, 0.0], [0.0, 1.0]]),
    ("leftright", 7, [[0.0, 0.0], [0.0, 1.0]]),
])
def test_balance_matrices(mode, value, expected):
    assert pl.balance_matrix(mode, value) == expected


def test_matrix_string_is_accepted_by_audiomixmatrix():
    element = Gst.ElementFactory.make("audiomixmatrix")
    element.set_property("in-channels", 2)
    element.set_property("out-channels", 2)
    Gst.util_set_object_arg(element, "matrix", pl.matrix_string(pl.balance_matrix("midside", 0.3)))


def test_effects_chain_starts(audio):
    pipeline = pl.Pipeline("fakesink")
    pipeline.set_balance("midside", -0.5)
    pipeline.set_file(uri(audio["left"]))
    pipeline.pause()
    try:
        assert pipeline.get_state(10 * Gst.SECOND)[0] == Gst.StateChangeReturn.SUCCESS
    finally:
        pipeline.set_state(Gst.State.NULL)


def export(source, path, speed=2.0, balance=("stereo", 0.0), limiter=True, section=None):
    """export with the given settings and wait for it; returns the error, or None"""
    pipeline = pl.Pipeline("fakesink")
    pipeline.set_speed(speed)
    pipeline.set_balance(*balance)
    pipeline.set_limiter(limiter)
    result = []
    pipeline.save_file(uri(source), str(path), result.append, section)
    assert run_until(lambda: result, 60), "the export did not finish"
    return result[0]


@pytest.mark.parametrize("extension", [".wav", ".mp3", ".ogg", ".flac"])
def test_export_formats_keep_length_and_channels(audio, tmp_path, extension):
    path = tmp_path / ("out" + extension)
    assert export(audio["left"], path) is None
    samples = decode(path)
    assert abs(len(samples) / 44100 - 3.0) < 0.1, "6 s at double speed should last 3 s"
    left, right = peak_db(samples)
    assert left > LOUD and right < SILENT


@pytest.mark.parametrize("balance, loud_left, loud_right", [
    (("stereo", 0.0), True, False),
    (("leftright", -1.0), True, False),
    (("balance", -1.0), True, True),
    (("balance", 1.0), False, False),
])
def test_balance_routes_the_channels(audio, tmp_path, balance, loud_left, loud_right):
    path = tmp_path / "out.wav"
    assert export(audio["left"], path, balance=balance) is None
    left, right = peak_db(decode(path))
    assert (left > LOUD) == loud_left and (right > LOUD) == loud_right


def test_side_only_halves_a_one_sided_tone(audio, tmp_path):
    stereo, side = tmp_path / "stereo.wav", tmp_path / "side.wav"
    export(audio["left"], stereo)
    export(audio["left"], side, balance=("midside", 1.0))
    reference = peak_db(decode(stereo))[0]
    for level in peak_db(decode(side)):
        assert abs(level - (reference - 6.02)) < 0.5


def test_section_export_covers_only_the_loop(audio, tmp_path):
    path = tmp_path / "section.wav"
    assert export(audio["left"], path, section=(1.0, 4.0)) is None
    assert abs(len(decode(path)) / 44100 - 1.5) < 0.1, "3 s of song at double speed should last 1.5 s"


def test_mp3_export_keeps_the_tags(audio, tmp_path):
    path = tmp_path / "tagged.mp3"
    assert export(audio["mp3"], path) is None
    tags = discover(path).get_tags()
    assert tags.get_string("title") == (True, "Practice Tune")
    assert tags.get_string("artist") == (True, "Test Band")


def test_limiter_keeps_peaks_below_full_scale(audio, tmp_path):
    limited, unlimited = tmp_path / "limited.wav", tmp_path / "unlimited.wav"
    export(audio["loud"], limited, speed=1.0)
    export(audio["loud"], unlimited, speed=1.0, limiter=False)
    assert max(peak_db(decode(limited))) < -0.7
    assert max(peak_db(decode(unlimited))) > -0.3


def test_export_reports_progress_and_cancel_removes_the_file(audio, tmp_path):
    pipeline = pl.Pipeline("fakesink")
    pipeline.set_speed(0.5)
    path = tmp_path / "long.wav"
    finished = []
    job = pipeline.save_file(uri(audio["long"]), str(path), finished.append)
    assert run_until(lambda: job.progress() > 0.05, 30)
    job.cancel()
    run_until(lambda: False, 0.5)
    assert not path.exists() and not finished and not pipeline.exports


@pytest.mark.parametrize("name", ["left", "mp3", "opus"])
def test_waveform_decodes_with_gstreamer(audio, name):
    extractor = WaveformExtractor(uri(audio[name]))
    assert extractor.samples.size > 0
    assert abs(float(abs(extractor.samples).max()) - 1.0) < 1e-6, "samples are normalized"
    assert len(extractor.get_samples(1000)) > 0
