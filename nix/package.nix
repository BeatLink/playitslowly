{
  lib,
  python3Packages,
  wrapGAppsHook3,
  gobject-introspection,
  gtk3,
  librsvg,
  gst_all_1,
  ffmpeg,
  yt-dlp,
}:

python3Packages.buildPythonApplication {
  pname = "playitslowly";
  version = "1.6.0";
  pyproject = false;

  src = lib.cleanSource ./..;

  nativeBuildInputs = [
    wrapGAppsHook3
    gobject-introspection
  ];

  buildInputs = [
    gtk3
    librsvg
    gst_all_1.gstreamer
    gst_all_1.gst-plugins-base
    gst_all_1.gst-plugins-good
    # Provides the soundtouch "pitch" element the app cannot run without.
    gst_all_1.gst-plugins-bad
    # Decodes AAC and other formats the plugin sets above leave out, such as most .m4a files.
    gst_all_1.gst-libav
  ];

  dependencies = with python3Packages; [
    pygobject3
    numpy
  ];

  installPhase = ''
    runHook preInstall
    make install PREFIX=$out PYTHONDIR=$out/${python3Packages.python.sitePackages}
    # A Python launcher, so the Python wrapper picks it up; it skips the shell script in bin/.
    cat > $out/bin/playitslowly <<EOF
    #!${python3Packages.python.interpreter}
    from playitslowly.app import main
    main()
    EOF
    chmod +x $out/bin/playitslowly
    runHook postInstall
  '';

  # Wrap once, with both the GApps and the Python environment.
  dontWrapGApps = true;
  # The YouTube dialog runs yt-dlp, which uses ffmpeg to strip the video container and tag the audio.
  # Desktops such as Cinnamon export a PYTHONPATH whose pygobject clashes with ours and breaks the window.
  preFixup = ''
    makeWrapperArgs+=("''${gappsWrapperArgs[@]}" --unset PYTHONPATH --prefix PATH : ${lib.makeBinPath [ ffmpeg yt-dlp ]})
  '';

  meta = {
    description = "Play back audio files at a different speed or pitch";
    homepage = "https://github.com/BeatLink/playitslowly";
    license = lib.licenses.gpl3Plus;
    mainProgram = "playitslowly";
    platforms = lib.platforms.linux;
  };
}
