#!/usr/bin/env python3
"""
MP3 Album Image Correction for Pioneer

Resizes embedded MP3 album art down to a max dimension (500px by default) and
converts PNG covers to JPEG, so the artwork shows up correctly on Pioneer CDJ
gear and in rekordbox. The audio is copied through untouched; only the artwork
is changed.

What it does:
- Drag and drop MP3 files or folders onto the window (needs tkinterdnd2; if
  that's not installed you use the buttons instead).
- Add Files / Add Folder buttons and paste paths with Ctrl+V.
- A queue with per-file status, remove, and clear, plus a right-click menu.
- Options for max size, JPEG quality, force PNG to JPEG, scan subfolders, and
  keeping a .bak backup.
- Progress bar and running counts.
- Processing runs on a background thread so the window stays responsive.
- Every run writes a log, and you can also export it from the File menu.

Requirements:
    pip install mutagen pillow tkinterdnd2

ffmpeg does the re-embedding. The app uses a bundled bin/ffmpeg.exe next to it
if present, otherwise ffmpeg on the system PATH.

tkinterdnd2 is optional. Without it you lose drag and drop but nothing else.
"""

import os
import sys
import queue
import shutil
import threading
import subprocess
import uuid
from datetime import datetime
from io import BytesIO

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# On a --windowed build, Windows pops up a console window for every ffmpeg
# call unless we pass CREATE_NO_WINDOW. The flag only exists on Windows, so
# elsewhere it stays 0 and does nothing.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0

# ----------------------------------------------------------------------------
# Optional imports
# ----------------------------------------------------------------------------
try:
    from PIL import Image
    HAVE_PIL = True
except Exception:                                    # pragma: no cover
    HAVE_PIL = False

try:
    from mutagen.id3 import ID3, ID3NoHeaderError
    HAVE_MUTAGEN = True
except Exception:                                    # pragma: no cover
    HAVE_MUTAGEN = False

try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    HAVE_DND = True
except Exception:                                    # pragma: no cover
    HAVE_DND = False


# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------
class Theme:
    BG        = "#12141c"
    PANEL     = "#1b1e2b"
    PANEL_ALT = "#232739"
    ACCENT    = "#5b8cff"
    ACCENT_HI = "#7aa2ff"
    TEXT      = "#e8eaf2"
    MUTED     = "#8a90a6"
    OK        = "#41d18b"
    WARN      = "#f0b429"
    ERR       = "#ff6b6b"
    SKIP      = "#8a90a6"
    BORDER    = "#2e3350"

STATUS_COLORS = {
    "queued":  Theme.MUTED,
    "working": Theme.ACCENT_HI,
    "passed":  Theme.OK,
    "skipped": Theme.SKIP,
    "failed":  Theme.ERR,
}


# ----------------------------------------------------------------------------
# Core image / mp3 logic
# ----------------------------------------------------------------------------
def _app_base_dir():
    """Folder to look in for a bundled ffmpeg.

    When frozen (one-file build), bundled files are unpacked to sys._MEIPASS.
    Run as a script, it's the folder this file is in.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """Path to a bundled resource such as the icon.

    Looks in sys._MEIPASS when frozen, otherwise next to this file.
    """
    base = getattr(sys, "_MEIPASS", None) or _app_base_dir()
    return os.path.join(base, name)


def _icon_path():
    """Path to the app icon on Windows if it exists, otherwise None.

    .ico is a Windows format, so we only bother on Windows. Returning None
    when there's no icon lets callers skip setting one.
    """
    if not sys.platform.startswith("win"):
        return None
    p = resource_path("icon.ico")
    return p if os.path.isfile(p) else None


def apply_window_icon(win, as_default=False):
    """Set the window icon. Does nothing if there's no icon.

    Pass as_default=True once on the root window. That makes the title bar,
    the taskbar button, and any dialogs (message boxes, file dialogs) use the
    icon too. Wrapped in try/except because a bad icon shouldn't crash the app.
    """
    path = _icon_path()
    if not path:
        return
    try:
        if as_default:
            win.iconbitmap(default=path)
        else:
            win.iconbitmap(path)
    except Exception:
        pass


def _exe_dir():
    """Folder that contains the running program, for the logs folder.

    This is different from _app_base_dir(): when frozen we want the folder
    holding the actual exe (sys.executable), not sys._MEIPASS, since _MEIPASS
    is a temp folder that gets wiped when the app exits. Run as a script, it's
    the script's own folder.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_logs_dir():
    """Return a writable 'logs' folder, creating it if needed.

    First choice is a 'logs' folder next to the exe so logs travel with the
    app. If that can't be written (say the app is in Program Files), fall back
    to a per-user folder. Returns None if neither can be created.
    """
    candidates = [os.path.join(_exe_dir(), "logs")]
    # Per-user fallback for protected install locations.
    if sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        candidates.append(os.path.join(base, "MP3AlbumImageCorrection", "logs"))
    else:
        candidates.append(os.path.join(os.path.expanduser("~"),
                                       ".mp3-album-image-correction", "logs"))
    for folder in candidates:
        try:
            os.makedirs(folder, exist_ok=True)
            # Confirm we can actually write here.
            probe = os.path.join(folder, ".writetest")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("")
            os.remove(probe)
            return folder
        except Exception:
            continue
    return None


class RunLogger:
    """Writes one timestamped log file per run into the logs folder.

    Each run gets its own resize_album_art_<timestamp>.log with the per-file
    results and a summary at the end. If the logs folder can't be written, it
    just skips logging rather than stopping the run.
    """

    def __init__(self):
        self.path = None
        self._fh = None
        folder = get_logs_dir()
        if not folder:
            return
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.path = os.path.join(folder, f"resize_album_art_{stamp}.log")
        try:
            self._fh = open(self.path, "a", encoding="utf-8")
        except Exception:
            self._fh = None
            self.path = None

    def _write(self, level, msg):
        if not self._fh:
            return
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._fh.write(f"{ts} - {level} - {msg}\n")
            self._fh.flush()
        except Exception:
            pass

    def info(self, msg):
        self._write("INFO", msg)

    def error(self, msg):
        self._write("ERROR", msg)

    def close(self):
        if self._fh:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None


def get_ffmpeg_path():
    """Find ffmpeg: bundled copy first, then PATH.

    Checks bin/ffmpeg(.exe) next to the app and uses it if it's there.
    Otherwise falls back to ffmpeg on PATH. Returns the path, or None if
    neither turns up.
    """
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    bundled = os.path.join(_app_base_dir(), "bin", exe)
    if os.path.isfile(bundled):
        return bundled
    on_path = shutil.which("ffmpeg")
    if on_path:
        return on_path
    return None


def ffmpeg_available():
    return get_ffmpeg_path() is not None


def resize_image_data(image_data, max_size=500, force_jpeg=True, quality=90):
    """Return (bytes, fmt, changed) or (None, None, "error string")."""
    try:
        with Image.open(BytesIO(image_data)) as img:
            width, height = img.size
            img_format = (img.format or "").upper()

            resize_needed = max(width, height) != max_size
            convert_needed = force_jpeg and img_format == "PNG"

            if resize_needed or convert_needed:
                if resize_needed:
                    if width >= height:
                        new_w = max_size
                        new_h = int((max_size / width) * height)
                    else:
                        new_h = max_size
                        new_w = int((max_size / height) * width)
                    img = img.resize((max(1, new_w), max(1, new_h)), Image.LANCZOS)

                out_io = BytesIO()
                img = img.convert("RGB")
                img.save(out_io, format="JPEG", quality=quality)
                return out_io.getvalue(), "JPEG", True

            return image_data, img_format, False
    except Exception as e:
        return None, None, f"Error resizing image: {e}"


def replace_album_art(file_path, image_data, keep_backup=False):
    folder = os.path.dirname(file_path) or "."
    uid = uuid.uuid4().hex
    temp_img = os.path.join(folder, f"temp_resized_art_{uid}.jpg")
    temp_out = os.path.join(folder, f"temp_output_{uid}.mp3")
    try:
        with open(temp_img, "wb") as f:
            f.write(image_data)

        cmd = [
            get_ffmpeg_path(), "-y",
            "-i", file_path,
            "-i", temp_img,
            "-map", "0:a",
            "-map", "1:v",
            "-c", "copy",
            "-id3v2_version", "3",
            "-metadata:s:v", "title=Album cover",
            "-metadata:s:v", "comment=Cover (front)",
            temp_out,
        ]
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            creationflags=_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, f"ffmpeg failed: {result.stderr.strip()[:400]}"

        if keep_backup:
            bak = file_path + ".bak"
            if not os.path.exists(bak):
                shutil.copy2(file_path, bak)

        os.replace(temp_out, file_path)
        return True, None
    except Exception as e:
        return False, f"Exception replacing album art: {e}"
    finally:
        for p in (temp_img, temp_out):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass


def process_mp3(file_path, max_size=500, force_jpeg=True, quality=90, keep_backup=False):
    """Return (status, message). status in passed/skipped/failed."""
    if not HAVE_MUTAGEN:
        return "failed", "mutagen not installed"
    if not HAVE_PIL:
        return "failed", "Pillow not installed"
    try:
        try:
            id3 = ID3(file_path)
        except ID3NoHeaderError:
            return "skipped", "No ID3 header / no artwork"

        apic_tags = id3.getall("APIC")
        if not apic_tags:
            return "skipped", "No embedded artwork"

        resized_data, _fmt, result = resize_image_data(
            apic_tags[0].data, max_size=max_size, force_jpeg=force_jpeg, quality=quality
        )
        if isinstance(result, str):
            return "failed", result
        if not result:
            return "skipped", "Already optimized"

        ok, err = replace_album_art(file_path, resized_data, keep_backup=keep_backup)
        if not ok:
            return "failed", err
        return "passed", "Updated"
    except Exception as e:
        return "failed", str(e)


def collect_mp3s(paths, recursive=True):
    """Expand a list of files/folders into a de-duplicated list of .mp3 paths."""
    found = []
    seen = set()

    def add(fp):
        ap = os.path.abspath(fp)
        if ap.lower().endswith(".mp3") and ap not in seen and os.path.isfile(ap):
            seen.add(ap)
            found.append(ap)

    for p in paths:
        p = p.strip().strip('"').strip("'")
        if not p:
            continue
        if os.path.isfile(p):
            add(p)
        elif os.path.isdir(p):
            if recursive:
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        add(os.path.join(root, f))
            else:
                for f in os.listdir(p):
                    add(os.path.join(p, f))
    return found


def parse_dnd_paths(data):
    """tkinterdnd2 gives a brace-wrapped, space-joined string. Parse it."""
    paths, buf, in_brace = [], "", False
    for ch in data:
        if ch == "{":
            in_brace = True
            buf = ""
        elif ch == "}":
            in_brace = False
            paths.append(buf)
            buf = ""
        elif ch == " " and not in_brace:
            if buf:
                paths.append(buf)
                buf = ""
        else:
            buf += ch
    if buf:
        paths.append(buf)
    return paths


# ----------------------------------------------------------------------------
# The GUI
# ----------------------------------------------------------------------------
class App:
    def __init__(self, root):
        self.root = root
        self.msg_q = queue.Queue()
        self.worker = None
        self.cancel_flag = threading.Event()
        self.rows = {}          # iid -> {"path":..., "status":...}

        root.title("MP3 Album Art Correction for Pioneer  v1.0.0.0")
        # default=True so the title bar, taskbar, and dialogs all use the icon
        apply_window_icon(root, as_default=True)
        root.geometry("980x680")
        root.minsize(820, 560)
        root.configure(bg=Theme.BG)

        self._build_style()
        self._build_menu()
        self._build_header()
        self._build_dropzone()
        self._build_options()
        self._build_table()
        self._build_controls()
        self._build_statusbar()

        self._register_dnd()
        self._check_environment()
        self.root.after(80, self._pump_queue)

    # ---- styling ------------------------------------------------------------
    def _build_style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("TFrame", background=Theme.BG)
        st.configure("Panel.TFrame", background=Theme.PANEL)
        st.configure("TLabel", background=Theme.BG, foreground=Theme.TEXT, font=("Segoe UI", 10))
        st.configure("Muted.TLabel", background=Theme.BG, foreground=Theme.MUTED, font=("Segoe UI", 9))
        st.configure("Head.TLabel", background=Theme.BG, foreground=Theme.TEXT, font=("Segoe UI Semibold", 16))
        st.configure("Panel.TLabel", background=Theme.PANEL, foreground=Theme.TEXT)
        st.configure("PanelMuted.TLabel", background=Theme.PANEL, foreground=Theme.MUTED, font=("Segoe UI", 9))

        st.configure("TCheckbutton", background=Theme.PANEL, foreground=Theme.TEXT,
                     font=("Segoe UI", 9), focuscolor=Theme.PANEL)
        st.map("TCheckbutton", background=[("active", Theme.PANEL)])

        st.configure("Accent.TButton", background=Theme.ACCENT, foreground="#0b1020",
                     font=("Segoe UI Semibold", 10), borderwidth=0, padding=(14, 8))
        st.map("Accent.TButton",
               background=[("active", Theme.ACCENT_HI), ("disabled", Theme.PANEL_ALT)],
               foreground=[("disabled", Theme.MUTED)])

        st.configure("Ghost.TButton", background=Theme.PANEL_ALT, foreground=Theme.TEXT,
                     font=("Segoe UI", 9), borderwidth=0, padding=(10, 6))
        st.map("Ghost.TButton", background=[("active", Theme.BORDER)])

        st.configure("Danger.TButton", background=Theme.PANEL_ALT, foreground=Theme.ERR,
                     font=("Segoe UI", 9), borderwidth=0, padding=(10, 6))
        st.map("Danger.TButton", background=[("active", "#3a2130")])

        st.configure("Treeview", background=Theme.PANEL, fieldbackground=Theme.PANEL,
                     foreground=Theme.TEXT, rowheight=26, borderwidth=0,
                     font=("Segoe UI", 9))
        st.configure("Treeview.Heading", background=Theme.PANEL_ALT, foreground=Theme.MUTED,
                     font=("Segoe UI Semibold", 9), borderwidth=0)
        st.map("Treeview.Heading", background=[("active", Theme.BORDER)])
        st.map("Treeview", background=[("selected", Theme.ACCENT)],
               foreground=[("selected", "#0b1020")])

        st.configure("TProgressbar", background=Theme.ACCENT, troughcolor=Theme.PANEL_ALT,
                     borderwidth=0, thickness=10)
        st.configure("Horizontal.TScale", background=Theme.PANEL)

    # ---- menu ---------------------------------------------------------------
    def _build_menu(self):
        m = tk.Menu(self.root)
        filem = tk.Menu(m, tearoff=0)
        filem.add_command(label="Add Files…", command=self.add_files, accelerator="Ctrl+O")
        filem.add_command(label="Add Folder…", command=self.add_folder, accelerator="Ctrl+D")
        filem.add_command(label="Paste paths", command=self.paste_paths, accelerator="Ctrl+V")
        filem.add_separator()
        filem.add_command(label="Export log…", command=self.export_log)
        filem.add_separator()
        filem.add_command(label="Quit", command=self.on_close)
        m.add_cascade(label="File", menu=filem)

        qm = tk.Menu(m, tearoff=0)
        qm.add_command(label="Remove selected", command=self.remove_selected, accelerator="Del")
        qm.add_command(label="Clear queue", command=self.clear_queue)
        m.add_cascade(label="Queue", menu=qm)

        helpm = tk.Menu(m, tearoff=0)
        helpm.add_command(label="About", command=self.show_about)
        m.add_cascade(label="Help", menu=helpm)
        self.root.config(menu=m)

        self.root.bind("<Control-o>", lambda e: self.add_files())
        self.root.bind("<Control-d>", lambda e: self.add_folder())
        self.root.bind("<Control-v>", lambda e: self.paste_paths())
        self.root.bind("<Delete>",    lambda e: self.remove_selected())

    # ---- header -------------------------------------------------------------
    def _build_header(self):
        head = ttk.Frame(self.root)
        head.pack(fill="x", padx=18, pady=(14, 6))
        ttk.Label(head, text="MP3 Album Art Corrector", style="Head.TLabel").pack(side="left")
        ttk.Label(head, text="  resize to 500 px · PNG → JPEG · Pioneer-ready",
                  style="Muted.TLabel").pack(side="left", padx=(8, 0), pady=(6, 0))

    # ---- drop zone ----------------------------------------------------------
    def _build_dropzone(self):
        wrap = ttk.Frame(self.root)
        wrap.pack(fill="x", padx=18, pady=(4, 6))
        self.drop = tk.Frame(wrap, bg=Theme.PANEL, highlightthickness=2,
                             highlightbackground=Theme.BORDER, height=92)
        self.drop.pack(fill="x")
        self.drop.pack_propagate(False)

        icon = "⬇" if HAVE_DND else "＋"
        main_txt = ("Drag & drop MP3 files or folders here"
                    if HAVE_DND else
                    "Add MP3 files or folders")
        self.drop_lbl = tk.Label(self.drop, text=f"{icon}  {main_txt}",
                                 bg=Theme.PANEL, fg=Theme.TEXT,
                                 font=("Segoe UI Semibold", 12))
        self.drop_lbl.pack(pady=(18, 2))

        sub = ("…or use the buttons below. Paste paths with Ctrl+V."
               if HAVE_DND else
               "Tip: install 'tkinterdnd2' to enable drag-and-drop.")
        self.drop_sub = tk.Label(self.drop, text=sub, bg=Theme.PANEL, fg=Theme.MUTED,
                                 font=("Segoe UI", 9))
        self.drop_sub.pack()

        for w in (self.drop, self.drop_lbl, self.drop_sub):
            w.bind("<Button-1>", lambda e: self.add_files())

    # ---- options bar --------------------------------------------------------
    def _build_options(self):
        opt = tk.Frame(self.root, bg=Theme.PANEL)
        opt.pack(fill="x", padx=18, pady=(2, 6))
        pad = {"padx": 10, "pady": 8}

        # Max size
        tk.Label(opt, text="Max size (px)", bg=Theme.PANEL, fg=Theme.MUTED,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w", **pad)
        self.max_size = tk.IntVar(value=500)
        self.size_spin = tk.Spinbox(opt, from_=64, to=2000, increment=10, width=6,
                                    textvariable=self.max_size, justify="center",
                                    bg=Theme.PANEL_ALT, fg=Theme.TEXT, buttonbackground=Theme.PANEL_ALT,
                                    relief="flat", insertbackground=Theme.TEXT,
                                    font=("Segoe UI", 10))
        self.size_spin.grid(row=0, column=1, sticky="w", pady=8)

        # JPEG quality
        tk.Label(opt, text="JPEG quality", bg=Theme.PANEL, fg=Theme.MUTED,
                 font=("Segoe UI", 9)).grid(row=0, column=2, sticky="w", **pad)
        self.quality = tk.IntVar(value=90)
        self.q_scale = ttk.Scale(opt, from_=50, to=100, variable=self.quality,
                                 command=lambda v: self.q_val.config(text=str(int(float(v)))),
                                 length=120)
        self.q_scale.grid(row=0, column=3, sticky="w", pady=8)
        self.q_val = tk.Label(opt, text="90", width=3, bg=Theme.PANEL, fg=Theme.TEXT,
                              font=("Segoe UI Semibold", 10))
        self.q_val.grid(row=0, column=4, sticky="w")

        # Checkboxes
        self.force_jpeg   = tk.BooleanVar(value=True)
        self.recursive    = tk.BooleanVar(value=True)
        self.keep_backup  = tk.BooleanVar(value=False)
        ttk.Checkbutton(opt, text="Force PNG → JPEG", variable=self.force_jpeg
                        ).grid(row=0, column=5, sticky="w", padx=14)
        ttk.Checkbutton(opt, text="Scan subfolders", variable=self.recursive
                        ).grid(row=0, column=6, sticky="w", padx=6)
        ttk.Checkbutton(opt, text="Keep .bak backup", variable=self.keep_backup
                        ).grid(row=0, column=7, sticky="w", padx=6)

    # ---- table --------------------------------------------------------------
    def _build_table(self):
        wrap = ttk.Frame(self.root)
        wrap.pack(fill="both", expand=True, padx=18, pady=(2, 4))

        cols = ("status", "file", "detail")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="extended")
        self.tree.heading("status", text="Status")
        self.tree.heading("file", text="File")
        self.tree.heading("detail", text="Detail")
        self.tree.column("status", width=90, anchor="w", stretch=False)
        self.tree.column("file", width=520, anchor="w")
        self.tree.column("detail", width=240, anchor="w")

        for name, col in STATUS_COLORS.items():
            self.tree.tag_configure(name, foreground=col)

        vsb = ttk.Scrollbar(wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # Right-click menu
        self.ctx = tk.Menu(self.tree, tearoff=0)
        self.ctx.add_command(label="Open containing folder", command=self._open_folder)
        self.ctx.add_command(label="Copy path", command=self._copy_path)
        self.ctx.add_separator()
        self.ctx.add_command(label="Remove", command=self.remove_selected)
        self.tree.bind("<Button-3>", self._popup_ctx)
        self.tree.bind("<Double-1>", lambda e: self._open_folder())

    # ---- control row --------------------------------------------------------
    def _build_controls(self):
        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=18, pady=(2, 4))

        ttk.Button(bar, text="Add Files", style="Ghost.TButton",
                   command=self.add_files).pack(side="left")
        ttk.Button(bar, text="Add Folder", style="Ghost.TButton",
                   command=self.add_folder).pack(side="left", padx=6)
        ttk.Button(bar, text="Remove", style="Ghost.TButton",
                   command=self.remove_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="Clear", style="Danger.TButton",
                   command=self.clear_queue).pack(side="left")

        self.run_btn = ttk.Button(bar, text="▶  Process", style="Accent.TButton",
                                  command=self.start_processing)
        self.run_btn.pack(side="right")
        self.cancel_btn = ttk.Button(bar, text="Cancel", style="Ghost.TButton",
                                     command=self.cancel_processing, state="disabled")
        self.cancel_btn.pack(side="right", padx=8)

    # ---- status bar ---------------------------------------------------------
    def _build_statusbar(self):
        sb = tk.Frame(self.root, bg=Theme.PANEL)
        sb.pack(fill="x", side="bottom")
        self.progress = ttk.Progressbar(sb, mode="determinate")
        self.progress.pack(fill="x", padx=12, pady=(8, 2))

        row = tk.Frame(sb, bg=Theme.PANEL)
        row.pack(fill="x", padx=12, pady=(0, 8))
        self.count_lbl = tk.Label(row, text="0 files queued", bg=Theme.PANEL,
                                  fg=Theme.MUTED, font=("Segoe UI", 9))
        self.count_lbl.pack(side="left")
        self.result_lbl = tk.Label(row, text="", bg=Theme.PANEL, fg=Theme.TEXT,
                                   font=("Segoe UI", 9))
        self.result_lbl.pack(side="right")

    # ------------------------------------------------------------------ DnD --
    def _register_dnd(self):
        if not HAVE_DND:
            return
        try:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)
            self.drop.dnd_bind("<<DropEnter>>", lambda e: self._drop_highlight(True))
            self.drop.dnd_bind("<<DropLeave>>", lambda e: self._drop_highlight(False))
            # also accept drops on the whole window
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind("<<Drop>>", self._on_drop)
        except Exception:
            pass

    def _drop_highlight(self, on):
        self.drop.configure(highlightbackground=Theme.ACCENT if on else Theme.BORDER)

    def _on_drop(self, event):
        self._drop_highlight(False)
        paths = parse_dnd_paths(event.data)
        self._ingest(paths)

    # --------------------------------------------------------------- actions -
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Select MP3 files",
            filetypes=[("MP3 files", "*.mp3"), ("All files", "*.*")])
        if files:
            self._ingest(list(files))

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select folder containing MP3 files")
        if folder:
            self._ingest([folder])

    def paste_paths(self):
        try:
            data = self.root.clipboard_get()
        except Exception:
            return
        parts = [p for p in data.replace("\r", "\n").split("\n") if p.strip()]
        if not parts:
            parts = data.split()
        self._ingest(parts)

    def _ingest(self, paths):
        mp3s = collect_mp3s(paths, recursive=self.recursive.get())
        added = 0
        existing = {self.rows[i]["path"] for i in self.rows}
        for fp in mp3s:
            if fp in existing:
                continue
            iid = self.tree.insert("", "end",
                                   values=("queued", fp, ""), tags=("queued",))
            self.rows[iid] = {"path": fp, "status": "queued"}
            existing.add(fp)
            added += 1
        self._refresh_counts()
        if added == 0 and paths:
            self.count_lbl.config(text="No new MP3s found in that selection")

    def remove_selected(self):
        for iid in self.tree.selection():
            self.tree.delete(iid)
            self.rows.pop(iid, None)
        self._refresh_counts()

    def clear_queue(self):
        if self.worker and self.worker.is_alive():
            return
        for iid in list(self.rows):
            self.tree.delete(iid)
        self.rows.clear()
        self.progress["value"] = 0
        self.result_lbl.config(text="")
        self._refresh_counts()

    def _refresh_counts(self):
        n = len(self.rows)
        self.count_lbl.config(text=f"{n} file{'s' if n != 1 else ''} queued")

    # ---- context menu helpers ----------------------------------------------
    def _popup_ctx(self, event):
        iid = self.tree.identify_row(event.y)
        if iid:
            if iid not in self.tree.selection():
                self.tree.selection_set(iid)
            self.ctx.tk_popup(event.x_root, event.y_root)

    def _selected_path(self):
        sel = self.tree.selection()
        if sel:
            return self.rows.get(sel[0], {}).get("path")
        return None

    def _open_folder(self):
        p = self._selected_path()
        if not p:
            return
        folder = os.path.dirname(p)
        try:
            if sys.platform.startswith("win"):
                os.startfile(folder)                      # noqa
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            messagebox.showinfo("Folder", folder)

    def _copy_path(self):
        p = self._selected_path()
        if p:
            self.root.clipboard_clear()
            self.root.clipboard_append(p)

    # --------------------------------------------------------------- process -
    def start_processing(self):
        if self.worker and self.worker.is_alive():
            return
        if not self.rows:
            messagebox.showinfo("Nothing to do", "Add some MP3 files first.")
            return
        if not ffmpeg_available():
            messagebox.showerror("ffmpeg missing",
                                 "ffmpeg could not be found.\n\n"
                                 "Expected a bundled copy at 'bin\\ffmpeg.exe' next to the app, "
                                 "or ffmpeg installed on your system PATH.\n"
                                 "Add one of those and try again.")
            return
        if not (HAVE_PIL and HAVE_MUTAGEN):
            missing = []
            if not HAVE_PIL:     missing.append("pillow")
            if not HAVE_MUTAGEN: missing.append("mutagen")
            messagebox.showerror("Missing packages",
                                 "Install: pip install " + " ".join(missing))
            return

        # Warn if any cover-affecting setting differs from the Pioneer spec
        # (500px, JPEG quality 90, PNG converted to JPEG). Anything off-spec,
        # in either direction, risks artwork the deck won't display. The other
        # options (scan subfolders, keep backup) don't affect the cover, so
        # they don't trigger this.
        size = int(self.max_size.get())
        quality = int(self.quality.get())
        force_jpeg = bool(self.force_jpeg.get())
        off_spec = []
        if size != 500:
            off_spec.append(
                f'- "Max size (px)" is {size}. The tested value is 500. '
                f'Set it back in the box at the top left.')
        if quality != 90:
            off_spec.append(
                f'- "JPEG quality" is {quality}. The tested value is 90. '
                f'Set it back with the slider at the top.')
        if not force_jpeg:
            off_spec.append(
                '- "Force PNG to JPEG" is off. Pioneer gear expects JPEG '
                'covers; PNG artwork may not display. Turn it back on.')
        if off_spec:
            msg = (
                "One or more settings differ from the values tested to work "
                "on Pioneer CDJ hardware:\n\n"
                + "\n\n".join(off_spec)
                + "\n\nAnything off-spec may load slowly or not show up at all "
                  "on the deck. You can set these back and try again, or "
                  "continue with the current settings.\n\n"
                  "Continue with the current settings?")
            if not messagebox.askyesno("Settings differ from the Pioneer spec", msg):
                return

        # reset statuses
        for iid, info in self.rows.items():
            info["status"] = "queued"
            self.tree.item(iid, values=("queued", info["path"], ""), tags=("queued",))

        self.cancel_flag.clear()
        self.run_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress["value"] = 0
        self.progress["maximum"] = len(self.rows)
        self.result_lbl.config(text="Working…")

        opts = dict(
            max_size=int(self.max_size.get()),
            force_jpeg=bool(self.force_jpeg.get()),
            quality=int(self.quality.get()),
            keep_backup=bool(self.keep_backup.get()),
        )
        items = list(self.rows.items())
        self.worker = threading.Thread(target=self._run_worker, args=(items, opts), daemon=True)
        self.worker.start()

    def cancel_processing(self):
        self.cancel_flag.set()
        self.result_lbl.config(text="Cancelling…")

    def _run_worker(self, items, opts):
        logger = RunLogger()
        started = datetime.now()
        logger.info(f"Run started: {len(items)} file(s) queued")
        logger.info("Options: max_size={max_size} force_jpeg={force_jpeg} "
                    "quality={quality} keep_backup={keep_backup}".format(**opts))
        stats = {"passed": 0, "skipped": 0, "failed": 0}
        failed_files = []
        log_path = logger.path
        try:
            for idx, (iid, info) in enumerate(items, start=1):
                if self.cancel_flag.is_set():
                    logger.info("Run cancelled by user")
                    self._log_summary(logger, stats, failed_files, started, cancelled=True)
                    logger.close()
                    self.msg_q.put(("done", stats, True, log_path))
                    return
                self.msg_q.put(("working", iid))
                status, detail = process_mp3(info["path"], **opts)
                stats[status] = stats.get(status, 0) + 1
                if status == "failed":
                    failed_files.append((info["path"], detail or ""))
                    logger.error(f"{info['path']} -> {detail}")
                else:
                    logger.info(f"[{status}] {info['path']}"
                                + (f" ({detail})" if detail else ""))
                self.msg_q.put(("result", iid, status, detail, idx))
            self._log_summary(logger, stats, failed_files, started, cancelled=False)
        finally:
            logger.close()
        self.msg_q.put(("done", stats, False, log_path))

    def _log_summary(self, logger, stats, failed_files, started, cancelled):
        elapsed = datetime.now() - started
        total = stats.get("passed", 0) + stats.get("skipped", 0) + stats.get("failed", 0)
        if failed_files:
            logger.info("Failures:")
            for path, reason in failed_files:
                logger.error(f"  {path} -> {reason}")
        logger.info(
            "Summary: "
            f"scanned={total} "
            f"updated={stats.get('passed', 0)} "
            f"skipped={stats.get('skipped', 0)} "
            f"failed={stats.get('failed', 0)} "
            f"elapsed={elapsed} "
            f"{'(cancelled)' if cancelled else ''}".rstrip())

    def _pump_queue(self):
        try:
            while True:
                msg = self.msg_q.get_nowait()
                kind = msg[0]
                if kind == "working":
                    iid = msg[1]
                    if iid in self.rows:
                        self.rows[iid]["status"] = "working"
                        self.tree.item(iid, values=("working", self.rows[iid]["path"], "…"),
                                       tags=("working",))
                        self.tree.see(iid)
                elif kind == "result":
                    _, iid, status, detail, idx = msg
                    if iid in self.rows:
                        self.rows[iid]["status"] = status
                        self.tree.item(iid, values=(status, self.rows[iid]["path"], detail or ""),
                                       tags=(status,))
                    self.progress["value"] = idx
                elif kind == "done":
                    stats, cancelled, log_path = msg[1], msg[2], msg[3]
                    self._finish(stats, cancelled, log_path)
        except queue.Empty:
            pass
        self.root.after(80, self._pump_queue)

    def _finish(self, stats, cancelled, log_path=None):
        self.run_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        self._last_log_path = log_path
        verb = "Cancelled" if cancelled else "Done"
        summary = (f"{verb} — {stats.get('passed',0)} updated · "
                   f"{stats.get('skipped',0)} skipped · {stats.get('failed',0)} failed")
        if log_path:
            summary += "  ·  log saved"
        self.result_lbl.config(text=summary)

    # ----------------------------------------------------------------- misc --
    def export_log(self):
        if not self.rows:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".log",
            filetypes=[("Log file", "*.log"), ("Text", "*.txt")],
            initialfile=f"album_art_{datetime.now():%Y-%m-%d_%H-%M-%S}.log")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"MP3 Album Art Corrector log — {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
                for iid, info in self.rows.items():
                    vals = self.tree.item(iid, "values")
                    f.write(f"[{vals[0]:>7}] {vals[1]}  {vals[2]}\n")
            messagebox.showinfo("Exported", f"Log written to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export failed", str(e))

    def _check_environment(self):
        problems = []
        if not HAVE_PIL:     problems.append("Pillow (pip install pillow)")
        if not HAVE_MUTAGEN: problems.append("mutagen (pip install mutagen)")
        if not ffmpeg_available(): problems.append("ffmpeg (bundle in bin\\ or add to PATH)")
        if problems:
            self.result_lbl.config(text="⚠ missing: " + ", ".join(p.split(" ")[0] for p in problems))
            self.drop_sub.config(
                text="Missing dependencies: " + ", ".join(problems),
                fg=Theme.WARN)

    def show_about(self):
        messagebox.showinfo(
            "About",
            "MP3 Album Art Corrector — GUI Edition\n\n"
            "Resizes embedded MP3 album art to a max dimension and converts\n"
            "PNG covers to JPEG for Pioneer CDJ / rekordbox compatibility.\n\n"
            "Based on the original script by Mr5niper (MIT License).\n"
            f"Drag & drop: {'enabled' if HAVE_DND else 'install tkinterdnd2 to enable'}")

    def on_close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Quit", "Processing is running. Quit anyway?"):
                return
            self.cancel_flag.set()
        self.root.destroy()


def _set_win_app_id():
    """Give the app its own taskbar identity on Windows.

    Without this, Windows lumps the window in with the Python host and shows
    Python's icon on the taskbar instead of ours. Setting an AppUserModelID
    fixes that. Windows only; if the call fails it's not worth crashing over.
    """
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "Mr5niper.MP3AlbumImageCorrection")
    except Exception:
        pass


def main():
    _set_win_app_id()
    if HAVE_DND:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
