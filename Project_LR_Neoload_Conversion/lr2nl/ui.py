"""Desktop UI (tkinter, ships with Python): pick folders, convert, see results and log."""
from __future__ import annotations

import os
import queue
import threading
import webbrowser

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import __version__
from .converter import convert_batch, discover_scripts

STATUS_COLORS = {"SUCCESS": "#1e7d32", "PARTIAL": "#b26a00", "FAILED": "#b71c1c"}


class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=10)
        master.title(f"LoadRunner to NeoLoad Converter - lr2nl {__version__}")
        master.geometry("980x640")
        master.minsize(760, 480)
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.src = tk.StringVar()
        self.out = tk.StringVar()
        self.users = tk.IntVar(value=1)
        self.duration = tk.StringVar(value="5m")
        self.status = tk.StringVar(value="Select a LoadRunner source folder and an output folder.")
        self._build()
        self.pack(fill="both", expand=True)
        self.after(100, self._poll)

    def _build(self) -> None:
        form = ttk.Frame(self)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        for row, (label, var, cmd) in enumerate((("LoadRunner source folder:", self.src, self._pick_src),
                                                 ("NeoLoad output folder:", self.out, self._pick_out))):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(form, textvariable=var).grid(row=row, column=1, sticky="ew", padx=6)
            ttk.Button(form, text="Browse...", command=cmd).grid(row=row, column=2)
        opts = ttk.Frame(self)
        opts.pack(fill="x", pady=(6, 6))
        ttk.Label(opts, text="Scenario users:").pack(side="left")
        ttk.Spinbox(opts, from_=1, to=10000, width=6, textvariable=self.users).pack(side="left", padx=(4, 12))
        ttk.Label(opts, text="Duration:").pack(side="left")
        ttk.Entry(opts, width=8, textvariable=self.duration).pack(side="left", padx=(4, 12))
        self.btn = ttk.Button(opts, text="Convert", command=self._convert)
        self.btn.pack(side="left")
        self.report_btn = ttk.Button(opts, text="Open HTML report", command=self._open_report, state="disabled")
        self.report_btn.pack(side="left", padx=6)
        ttk.Button(opts, text="Open output folder", command=self._open_out).pack(side="left")
        self.progress = ttk.Progressbar(opts, mode="determinate", length=180)
        self.progress.pack(side="right")

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        grid_frame = ttk.Frame(panes)
        cols = ("script", "status", "pct", "review")
        self.grid = ttk.Treeview(grid_frame, columns=cols, show="headings", height=12)
        for col, title, width, anchor in (("script", "Script Name", 420, "w"), ("status", "Conversion Status", 140, "center"),
                                          ("pct", "Success %", 100, "e"), ("review", "Items to review", 120, "e")):
            self.grid.heading(col, text=title)
            self.grid.column(col, width=width, anchor=anchor)
        for status, color in STATUS_COLORS.items():
            self.grid.tag_configure(status, foreground=color)
        sb = ttk.Scrollbar(grid_frame, orient="vertical", command=self.grid.yview)
        self.grid.configure(yscrollcommand=sb.set)
        self.grid.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        panes.add(grid_frame, weight=3)
        log_frame = ttk.LabelFrame(panes, text="Log")
        self.log = ScrolledText(log_frame, height=8, state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True)
        panes.add(log_frame, weight=2)
        ttk.Label(self, textvariable=self.status, anchor="w").pack(fill="x", pady=(6, 0))

    def _pick_src(self) -> None:
        d = filedialog.askdirectory(title="Select the LoadRunner script folder (or a folder of scripts)")
        if d:
            self.src.set(os.path.normpath(d))
            if not self.out.get():
                self.out.set(os.path.normpath(d.rstrip("/\\") + "_neoload"))
            n = len(discover_scripts(d))
            self.status.set(f"{n} LoadRunner script(s) found in the source folder.")

    def _pick_out(self) -> None:
        d = filedialog.askdirectory(title="Select the output folder")
        if d:
            self.out.set(os.path.normpath(d))

    def _write_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _convert(self) -> None:
        src, out = self.src.get().strip(), self.out.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror("lr2nl", "Select an existing LoadRunner source folder.")
            return
        if not out:
            messagebox.showerror("lr2nl", "Select an output folder.")
            return
        if os.path.abspath(out).startswith(os.path.abspath(src) + os.sep):
            messagebox.showerror("lr2nl", "The output folder must not be inside the source folder.")
            return
        total = len(discover_scripts(src))
        if total == 0:
            messagebox.showwarning("lr2nl", "No LoadRunner scripts found (looking for Action.c / vuser_init.c / .usr).")
            return
        try:
            users = int(self.users.get())
        except (tk.TclError, ValueError):
            users = 1
        self.grid.delete(*self.grid.get_children())
        self.progress.configure(maximum=total, value=0)
        self.btn.configure(state="disabled")
        self.report_btn.configure(state="disabled")
        self.status.set(f"Converting {total} script(s)...")

        def work() -> None:
            try:
                results = convert_batch(src, out, users, self.duration.get().strip() or "5m",
                                        log=lambda m: self.q.put(("log", m)),
                                        on_result=lambda r: self.q.put(("result", r)))
                self.q.put(("done", results))
            except Exception as exc:
                self.q.put(("error", str(exc)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._write_log(payload)
                elif kind == "result":
                    r = payload
                    self.grid.insert("", "end", values=(r.name, r.status, f"{r.pct:.1f}%", r.review_items), tags=(r.status,))
                    self.progress.step(1)
                elif kind == "done":
                    res = payload
                    counts = {s: sum(1 for r in res if r.status == s) for s in STATUS_COLORS}
                    self.status.set(f"Done: {len(res)} script(s) - {counts['SUCCESS']} success, "
                                    f"{counts['PARTIAL']} partial, {counts['FAILED']} failed.")
                    self.btn.configure(state="normal")
                    self.report_btn.configure(state="normal")
                elif kind == "error":
                    self._write_log("ERROR: " + payload)
                    self.status.set("Conversion failed - see log.")
                    self.btn.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _open_report(self) -> None:
        path = os.path.join(self.out.get(), "reports", "conversion_report.html")
        if os.path.isfile(path):
            webbrowser.open("file:///" + os.path.abspath(path).replace("\\", "/"))

    def _open_out(self) -> None:
        path = self.out.get()
        if path and os.path.isdir(path):
            if hasattr(os, "startfile"):
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open("file://" + os.path.abspath(path))


def run_ui() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    run_ui()
