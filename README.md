MP3 Album Art Corrector (GUI)

A desktop app that resizes embedded MP3 album art to a max size (default 500px)
and converts PNG covers to JPEG so they show up correctly on Pioneer CDJ gear
and in rekordbox. It's a GUI version of the original command-line script.


Features

- Drag and drop MP3 files or whole folders onto the window (needs tkinterdnd2,
  see below). If that package isn't installed, the app still works, you just
  use the buttons instead.
- Add Files and Add Folder buttons, plus paste file paths with Ctrl+V.
- A queue list that shows each file's status: queued, working, passed,
  skipped, or failed.
- Right-click a row to open its folder or copy its path. Double-click opens
  the folder.
- Options:
  - Max size in pixels (default 500)
  - JPEG quality slider (50 to 100)
  - Force PNG to JPEG on/off
  - Scan subfolders on/off
  - Keep a .bak backup of every file it changes
- Progress bar and a running count of updated / skipped / failed.
- Cancel button to stop a run partway through.
- Export the results to a .log or .txt file.
- Checks for ffmpeg, Pillow, and mutagen on startup and tells you if
  something is missing instead of crashing.


ffmpeg

The app uses ffmpeg to re-embed the artwork. It looks for ffmpeg in two places,
in this order:

  1. A bundled copy at bin\ffmpeg.exe next to the app (the built .exe ships
     with this).
  2. ffmpeg on your system PATH (used when you run the .py script directly and
     have ffmpeg installed).

So the built .exe is self-contained and needs nothing installed. If you run the
raw Python script instead, either drop an ffmpeg.exe in a bin folder next to it
or have ffmpeg on your PATH.


Running the Python script

- Python 3.13.12 (the build is pinned to this version)
- Python packages:

    pip install mutagen pillow tkinterdnd2

  tkinterdnd2 is optional. It's only needed for drag and drop. Everything else
  works without it.

- ffmpeg available (see the ffmpeg section above)

Then run:

    python "MP3 Album Image Correction for Pioneer (500x500jpg).py"

Drag in some MP3s or folders (or use Add Files / Add Folder), change any options
you want, and click Process.


Building the .exe

The build produces a single self-contained .exe with ffmpeg bundled inside.

1. Install Python 3.13.12 and add it to PATH.
2. Put an ffmpeg.exe at bin\ffmpeg.exe next to BUILD_EXE.bat. Use an LGPL build
   (not a GPL or nonfree build) so the release stays redistributable. See the
   NOTICE file for details.
3. Optional: put an icon.ico next to BUILD_EXE.bat to set the app icon.
4. Double-click BUILD_EXE.bat.

The finished .exe lands in the dist folder. The build script creates a venv,
installs the pinned dependencies from requirements.txt, and runs PyInstaller
with the right options (windowed, tkinter and tkinterdnd2 collected, ffmpeg and
icon bundled, version info embedded).


Notes

- The app changes files in place. The audio is copied straight through and is
  never re-encoded, so sound quality is untouched. Only the artwork gets
  resized or converted. Turn on "Keep .bak backup" if you want a safety copy.
- Only the first embedded image in each file is processed. This matches the
  original script.


License

MIT License for this app. Based on the original script by Mr5niper. See the
LICENSE file. Bundled ffmpeg is licensed separately under the LGPL; see NOTICE.
