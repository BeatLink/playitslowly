# Runs the test suite in the build sandbox, playing into silent sinks under a virtual display.
{
  lib,
  stdenv,
  python3,
  xvfb-run,
  gobject-introspection,
  gtk3,
  gst_all_1,
}:

stdenv.mkDerivation {
  name = "playitslowly-tests";
  src = lib.cleanSource ./..;

  nativeBuildInputs = [
    xvfb-run
    gobject-introspection
    (python3.withPackages (p: [
      p.pygobject3
      p.numpy
      p.pytest
    ]))
  ];

  buildInputs = [
    gtk3
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
    gst_all_1.gst-plugins-good
    gst_all_1.gst-plugins-bad
  ];

  dontConfigure = true;
  buildPhase = ''
    export HOME=$TMPDIR XDG_CONFIG_HOME=$TMPDIR/config
    xvfb-run -a python -m pytest -p no:cacheprovider tests
  '';
  installPhase = "touch $out";
}
