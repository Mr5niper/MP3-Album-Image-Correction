import os
import logging
from datetime import datetime
from mutagen.id3 import ID3, APIC, ID3NoHeaderError
from PIL import Image
from io import BytesIO
from tkinter import Tk, filedialog
import subprocess
import uuid

# Generate timestamped log file name
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
log_file = f"resize_album_art_{timestamp}.log"
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding='utf-8'
)

def log_print(msg, level="info"):
    if level == "error":
        logging.error(msg)
    elif level == "info":
        logging.info(msg)

def resize_image_data(image_data, max_size=500):
    try:
        with Image.open(BytesIO(image_data)) as img:
            width, height = img.size
            img_format = img.format.upper()

            # Decide if resize needed
            resize_needed = max(width, height) != max_size

            # Always convert PNG to JPEG
            if img_format == "PNG" or resize_needed:
                if resize_needed:
                    if width >= height:
                        new_width = max_size
                        new_height = int((max_size / width) * height)
                    else:
                        new_height = max_size
                        new_width = int((max_size / height) * width)
                    img = img.resize((new_width, new_height), Image.LANCZOS)

                out_io = BytesIO()
                # Save as JPEG in all cases here
                img = img.convert("RGB")  # Convert PNG transparency to RGB
                img.save(out_io, format="JPEG")
                return out_io.getvalue(), "JPEG", True

            # No resize needed and not PNG, just return original
            return image_data, img_format, False

    except Exception as e:
        return None, None, f"Error resizing image: {e}"

def replace_album_art(file_path, image_data, img_format):
    folder = os.path.dirname(file_path)
    unique_id = uuid.uuid4().hex
    temp_img = os.path.join(folder, f"temp_resized_art_{unique_id}.jpg")
    temp_out = os.path.join(folder, f"temp_output_{unique_id}.mp3")

    try:
        with open(temp_img, "wb") as f:
            f.write(image_data)

        cmd = [
            "ffmpeg",
            "-y",
            "-i", file_path,
            "-i", temp_img,
            "-map", "0:a",
            "-map", "1:v",
            "-c", "copy",
            "-id3v2_version", "3",
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)",
            temp_out
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")

        if result.returncode != 0:
            error_msg = f"ffmpeg failed for '{file_path}': {result.stderr.strip()}"
            return False, error_msg

        os.replace(temp_out, file_path)
        return True, None

    except Exception as e:
        return False, f"Exception replacing album art: {e}"

    finally:
        if os.path.exists(temp_img):
            os.remove(temp_img)
        if os.path.exists(temp_out):
            try:
                os.remove(temp_out)
            except Exception:
                pass

def process_mp3(file_path):
    try:
        try:
            id3 = ID3(file_path)
        except ID3NoHeaderError:
            id3 = ID3()

        apic_tags = id3.getall("APIC")
        if not apic_tags:
            return "skipped", None  # No image to resize

        original_apic = apic_tags[0]
        resized_data, img_format, result = resize_image_data(original_apic.data)

        if isinstance(result, str):
            return "failed", result  # Resize error
        if not result:
            return "skipped", None  # No resizing needed

        success, err = replace_album_art(file_path, resized_data, img_format)
        if not success:
            return "failed", err

        return "passed", None

    except Exception as e:
        return "failed", str(e)

def select_folder():
    root = Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    folder_path = filedialog.askdirectory(title="Select Folder Containing MP3 Files")
    root.destroy()
    return folder_path

def main():
    start_time = datetime.now()
    folder = select_folder()
    if not folder:
        return

    all_folders = [os.path.join(folder, d) for d in os.listdir(folder) if os.path.isdir(os.path.join(folder, d))]
    total_folders = len(all_folders)
    folders_done = 0

    total_files = 0
    passes = 0
    failures = 0
    skipped = 0
    failed_files = []

    for subfolder in all_folders:
        for root_dir, _, files in os.walk(subfolder):
            for f in files:
                if f.lower().endswith(".mp3"):
                    total_files += 1
                    file_path = os.path.join(root_dir, f)
                    result, err_msg = process_mp3(file_path)
                    if result == "passed":
                        passes += 1
                    elif result == "skipped":
                        skipped += 1
                    elif result == "failed":
                        failures += 1
                        failed_files.append((file_path, err_msg))

        folders_done += 1
        print(f"\r{(folders_done / total_folders) * 100:.1f}% complete", end="", flush=True)
    end_time = datetime.now()

    # Write only failure details and summary to log
    if failures > 0:
        for f, reason in failed_files:
            log_print(f"{f} -> {reason}", "error")

    summary = (
        f"Summary:\n"
        f"  Files scanned: {total_files}\n"
        f"  Successfully updated: {passes}\n"
        f"  Skipped (no resize needed): {skipped}\n"
        f"  Failed: {failures}"
    )
    log_print(summary, "info")

if __name__ == "__main__":
    main()
