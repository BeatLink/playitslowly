{
  lib,
  python3Packages,
  wrapGAppsHook3,
  gobject-introspection,
  gtk3,
  librsvg,
  gst_all_1,
}:

python3Packages.buildPythonApplication {
  pname = "playitslowly";
  version = "1.5.1";
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
  ];

  dependencies = [ python3Packages.pygobject3 ];

  # setup.py needs distutils, which current Python no longer ships, so install the files directly.
  installPhase = ''
    runHook preInstall
    mkdir -p $out/bin $out/${python3Packages.python.sitePackages}
    cp -r playitslowly $out/${python3Packages.python.sitePackages}/
    cp -r share $out/
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
  # Desktops such as Cinnamon export a PYTHONPATH whose pygobject clashes with ours and breaks the window.
  preFixup = ''
    makeWrapperArgs+=("''${gappsWrapperArgs[@]}" --unset PYTHONPATH)
  '';

  meta = {
    description = "Play back audio files at a different speed or pitch";
    homepage = "https://github.com/BeatLink/playitslowly";
    license = lib.licenses.gpl3Plus;
    mainProgram = "playitslowly";
    platforms = lib.platforms.linux;
  };
}
