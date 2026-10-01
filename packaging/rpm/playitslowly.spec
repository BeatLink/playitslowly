Name:           playitslowly
Version:        1.6.1
Release:        1%{?dist}
Summary:        Play music slower or at another pitch for practice
License:        GPL-3.0-or-later
URL:            https://github.com/BeatLink/playitslowly
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make
BuildRequires:  python3-devel
BuildRequires:  desktop-file-utils
BuildRequires:  libappstream-glib

Requires:       python3-gobject
Requires:       python3-numpy
Requires:       gtk3
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       gstreamer1-plugins-bad-free
# The soundtouch "pitch" element lives in the extras subpackage.
Requires:       gstreamer1-plugins-bad-free-extras
Recommends:     yt-dlp
Recommends:     ffmpeg-free

%description
Play it Slowly plays an audio file at a different speed without changing its
pitch, or at a different pitch without changing its speed. It helps musicians
learn and transcribe music. It loops a section shown on a waveform, offers
balance and mid/side modes, a count-in and number pad shortcuts, downloads the
audio of YouTube videos and saves the result as WAV, MP3, Ogg Vorbis or FLAC.

%prep
%autosetup

%build

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix} PYTHONDIR=%{python3_sitelib}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/ch.x29a.playitslowly.desktop
appstream-util validate-relax --nonet %{buildroot}%{_metainfodir}/ch.x29a.playitslowly.metainfo.xml

%files
%license COPYING
%doc README.rst CHANGELOG
%{_bindir}/playitslowly
%{python3_sitelib}/playitslowly/
%{_datadir}/applications/ch.x29a.playitslowly.desktop
%{_metainfodir}/ch.x29a.playitslowly.metainfo.xml
%{_datadir}/icons/hicolor/*/apps/ch.x29a.playitslowly.*

%changelog
* Thu Oct 01 2026 Play it Slowly maintainers <BeatLink@users.noreply.github.com> - 1.6.1-1
- Label the waveform height slider

* Wed Sep 30 2026 Play it Slowly maintainers <BeatLink@users.noreply.github.com> - 1.6.0-1
- First release of the maintained fork
