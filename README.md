# MP3 Album Art Corrector (GUI)

A desktop app that resizes embedded MP3 album art to a max size (default 500px)
and converts PNG covers to JPEG so they show up correctly on Pioneer CDJ gear
and in rekordbox.

<img width="1429" height="1073" alt="image" src="https://github.com/user-attachments/assets/bba28b50-c1d1-47f3-b88a-d70d7a608028" />
<br>
<br>

## Features

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
<br> 
<br>

## ffmpeg

The app uses ffmpeg to re-embed the artwork. At runtime it looks for ffmpeg in
two places, in this order:

  1. A bundled copy at bin\ffmpeg.exe next to the app (the built .exe ships
     with this).
  2. ffmpeg on your system PATH (used when you run the .py script directly and
     have ffmpeg installed).

So the built .exe is self-contained and needs nothing installed. If you run the
raw Python script instead, either drop an ffmpeg.exe in a bin folder next to it
or have ffmpeg on your PATH.

The build gets ffmpeg automatically: if bin\ffmpeg.exe is missing, BUILD_EXE.bat
downloads the current LGPL build from BtbN and extracts ffmpeg.exe into bin.
Because BtbN's "latest" always serves the newest build, a fresh build may get a
newer ffmpeg than the one this project was tested with; the build prints a
warning when that happens but still continues. Only an LGPL build is used, so
the result stays redistributable. See the NOTICE file for the tested version
and the licensing terms.
<br>
<br>

## Running the Python script

- Python 3.13.12 (the build is pinned to this version)
- Python packages:

    pip install mutagen pillow tkinterdnd2

  tkinterdnd2 is optional. It's only needed for drag and drop. Everything else
  works without it.

- ffmpeg available (see the ffmpeg section above)

Then run:

    python "MP3 Album Image Correction for Pioneer.py"

Drag in some MP3s or folders (or use Add Files / Add Folder), change any options
you want, and click Process.
<br>
<br>

## Building the .exe

The build produces a single self-contained .exe with ffmpeg bundled inside.

1. Install Python 3.13.12 and add it to PATH.
2. ffmpeg: if you already have a tested bin\ffmpeg.exe, leave it in place and
   the build uses it. Otherwise the build downloads the current LGPL build from
   BtbN automatically. (It uses an LGPL build so the release stays
   redistributable; see NOTICE.)
3. Optional: put an icon.ico next to BUILD_EXE.bat to set the app icon.
4. Double-click BUILD_EXE.bat.

The finished .exe lands in the dist folder. The build script creates a venv,
installs the pinned dependencies from requirements.txt, ensures ffmpeg is in
bin, and runs PyInstaller with the right options (windowed, tkinter and
tkinterdnd2 collected, ffmpeg and icon bundled, version info embedded).
<br>
<br>

## Notes

- Every run writes a timestamped log to a "logs" folder created next to the
  app (for the built exe, next to the .exe; when run as a script, next to the
  script). Each log lists the options used, a line per file (updated / skipped
  / failed), and a summary with counts and elapsed time. If that folder can't
  be written (for example the app is in Program Files), logs fall back to a
  per-user location so logging still works. You can also still use File >
  Export log to save a copy wherever you want.
- The app changes files in place. The audio is copied straight through and is
  never re-encoded, so sound quality is untouched. Only the artwork gets
  resized or converted. Turn on "Keep .bak backup" if you want a safety copy.
- Only the first embedded image in each file is processed.
<br>
<br>

## License

MIT License. Created by Mr5niper. See the LICENSE file. Bundled ffmpeg is
licensed separately under the LGPL; see NOTICE.
