#!/usr/bin/env python3
"""
MP3 Album Art Corrector — GUI Edition
=====================================
A desktop GUI wrapper around the original "MP3 Album Image Correction for
Pioneer (500x500 jpg)" script.

Resizes embedded MP3 album art to a max dimension (default 500 px) and converts
PNG covers to JPEG so they play nicely with Pioneer CDJ / rekordbox hardware.

Features
--------
* Drag & drop MP3 files or whole folders onto the window (needs tkinterdnd2;
  falls back gracefully to buttons if it isn't installed).
* Add Files / Add Folder buttons + paste-from-clipboard (Ctrl+V).
* A reorderable queue with per-file status, remove / clear, right-click menu.
* Adjustable max size, recursive-scan toggle, "force JPEG" toggle,
  "keep backup (.bak)" toggle, JPEG quality slider.
* Live progress bar, running counters, and a searchable results log.
* Runs the heavy work on a background thread so the UI never freezes.
* Export the log to a .txt / .log file.

Requirements
------------
    pip install mutagen pillow tkinterdnd2

ffmpeg is used to re-embed the artwork. The app looks for a bundled copy at
'bin/ffmpeg.exe' next to it first, and otherwise falls back to ffmpeg on the
system PATH.

tkinterdnd2 is OPTIONAL — the app still works without it, you just lose the
drag-and-drop surface (everything else remains).
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

# On Windows, a --windowed (no-console) build would otherwise flash a black
# console window for every ffmpeg call. CREATE_NO_WINDOW suppresses that.
# On macOS/Linux this flag doesn't exist, so it stays 0 (a harmless no-op).
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform.startswith("win") else 0

# ----------------------------------------------------------------------------
# Optional / graceful dependency handling
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
# Core image / mp3 logic (ported from the original script)
# ----------------------------------------------------------------------------
def _app_base_dir():
    """Folder to look in for a bundled ffmpeg.

    When frozen by PyInstaller (one-file), bundled data lives in a temp dir
    exposed as sys._MEIPASS. When run as a normal script, it's the folder the
    script lives in.
    """
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """Locate a bundled resource file (e.g. the app icon).

    When frozen by PyInstaller, resources are extracted to sys._MEIPASS. When
    run as a normal script, they sit next to this file. Returns the full path.
    """
    base = getattr(sys, "_MEIPASS", None) or _app_base_dir()
    return os.path.join(base, name)


def _icon_path():
    """Full path to the app icon if it exists and we're on Windows, else None.

    .ico is a Windows format; iconbitmap expects it there. On other platforms we
    skip it so we don't raise.
    """
    if not sys.platform.startswith("win"):
        return None
    p = resource_path("icon.ico")
    return p if os.path.isfile(p) else None


def apply_window_icon(win, as_default=False):
    """Set the icon on a Tk window/dialog. Best-effort; never raises.

    as_default=True (used once on the root) applies the icon to the whole
    application, so the title bar, the taskbar button, and every child dialog
    (messageboxes, file dialogs, Toplevels) inherit it.
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


def get_ffmpeg_path():
    """Return a usable ffmpeg command.

    Preference order:
      1. A bundled binary at <base>/bin/ffmpeg(.exe)  (shipped with the app)
      2. ffmpeg found on the system PATH
    Returns the full path to the bundled binary if present, otherwise the bare
    name "ffmpeg" (resolved via PATH by the OS), or None if nothing is found.
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

        root.title("MP3 Album Art Corrector — Pioneer 500×500")
        # Apply the icon to the whole app: title bar, taskbar button, and every
        # child dialog (messageboxes, file dialogs) inherits it via default=.
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
        stats = {"passed": 0, "skipped": 0, "failed": 0}
        for idx, (iid, info) in enumerate(items, start=1):
            if self.cancel_flag.is_set():
                self.msg_q.put(("done", stats, True))
                return
            self.msg_q.put(("working", iid))
            status, detail = process_mp3(info["path"], **opts)
            stats[status] = stats.get(status, 0) + 1
            self.msg_q.put(("result", iid, status, detail, idx))
        self.msg_q.put(("done", stats, False))

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
                    stats, cancelled = msg[1], msg[2]
                    self._finish(stats, cancelled)
        except queue.Empty:
            pass
        self.root.after(80, self._pump_queue)

    def _finish(self, stats, cancelled):
        self.run_btn.config(state="normal")
        self.cancel_btn.config(state="disabled")
        verb = "Cancelled" if cancelled else "Done"
        self.result_lbl.config(
            text=f"{verb} — {stats.get('passed',0)} updated · "
                 f"{stats.get('skipped',0)} skipped · {stats.get('failed',0)} failed")

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

    Without an explicit AppUserModelID, Windows may group the window under the
    Python/pythonw host and show its icon in the taskbar instead of ours. Setting
    a distinct ID makes the taskbar use this app's own icon. Best-effort no-op
    elsewhere or on failure.
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
