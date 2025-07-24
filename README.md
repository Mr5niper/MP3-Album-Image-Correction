🎵 MP3 Album Art Resizer
This Python script scans through subfolders of a selected directory, identifies MP3 files with embedded album art, and resizes the artwork to a maximum dimension (default: 500px). It also converts PNG covers to JPEG for better compatibility and consistency.

📦 Features
- Automatically detects and resizes embedded album art in MP3 files.
- Converts PNG images to JPEG.
- Uses ffmpeg to re-embed resized artwork without re-encoding audio.
- Logs all operations with timestamps.
- Skips files with no embedded artwork or already optimized images.

🛠️ Requirements

- Python 3.7+
- ffmpeg (must be installed and accessible via system PATH)

    Python Dependencies
Install required packages using pip:

        pip install mutagen pillow

🚀 Usage

1.	Run the script:

2.	A folder selection dialog will appear. Choose the root folder containing subfolders with MP3 files.

3.	The script will:

    -    Traverse all subdirectories.

    -    Resize and convert album art where needed.

    -    Log results to a timestamped .log file.

📁 Log Output

A log file named like resize_album_art_YYYY-MM-DD_HH-MM-SS.log will be created in the script's directory. It includes:

-    Files processed
    
-    Successes and failures

-    Summary statistics

🧪 Example
Summary:
  
-    Files scanned: 120
  
-    Successfully updated: 45
  
-    Skipped (no resize needed): 70
  
-    Failed: 5

⚠️ Notes

This script modifies files in place. Consider backing up your MP3s before running.
    
Only the first embedded image is processed per file.
    
Requires write permissions in the target directories.

📄 License
MIT License
