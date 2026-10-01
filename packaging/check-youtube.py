"""Downloads a short public video's audio with the app's YouTube code and decodes it, without opening a window."""

import os
import sys
import tempfile

from playitslowly import app  # noqa: F401  sets up GStreamer the way the app does
from playitslowly import youtube
from playitslowly.waveform import WaveformExtractor
from gi.repository import GLib

url = sys.argv[1] if len(sys.argv) > 1 else "https://www.youtube.com/watch?v=jNQXAC9IVRw"
target = tempfile.mkdtemp()
youtube.download_dir = lambda: target
loop = GLib.MainLoop()
result = {}


def done(path, error):
    result.update(path=path, error=error)
    loop.quit()


youtube.Download(url, lambda fraction: None, done)
GLib.timeout_add_seconds(240, loop.quit)
loop.run()
if not result.get("path"):
    sys.exit("youtube check: the download failed: %s" % result.get("error", "timed out"))
samples = WaveformExtractor(GLib.filename_to_uri(result["path"], None)).get_samples(1000)
if len(samples) == 0:
    sys.exit("youtube check: the download could not be decoded")
print("youtube check: passed,", os.path.basename(result["path"]))
