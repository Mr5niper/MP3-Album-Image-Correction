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


Requirements

- Python 3.7 or newer
- ffmpeg installed and on your system PATH
- Python packages:

    pip install mutagen pillow tkinterdnd2

tkinterdnd2 is optional. It's only needed for drag and drop. Everything else
works without it.

On some Linux systems you may also need the Tk package for Python:

    sudo apt install python3-tk


How to run

    python "MP3 Album Image Correction for Pioneer (500x500jpg).py"

Then drag in some MP3s or folders (or use Add Files / Add Folder), change any
options you want, and click Process.


Notes

- The app changes files in place. The audio is copied straight through and is
  never re-encoded, so sound quality is untouched. Only the artwork gets
  resized or converted. Turn on "Keep .bak backup" if you want a safety copy.
- Only the first embedded image in each file is processed. This matches the
  original script.


License

MIT License. Based on the original script by Mr5niper. See the LICENSE file.
