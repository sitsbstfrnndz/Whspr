import os
import platform
import signal
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk


def load_dotenv():
    try:
        dotenv_module = __import__("dotenv")
        return getattr(dotenv_module, "load_dotenv")()
    except Exception:
        return False


# Load .env first so module-level config defaults pick up local settings.
load_dotenv()

AUDIO_LOGS_DIR = Path(os.path.expanduser("~/AudioLogs"))
PROJECT_DIR = Path(__file__).resolve().parent
REALTIME_SCRIPT = PROJECT_DIR / "realtime_prototype.py"
CHUNKED_SCRIPT = PROJECT_DIR / "chunked_transcribe.py"
REFRESH_MS = 1200
MAX_VIEW_CHARS = 8000
AUTO_START_ON_LAUNCH = os.getenv("AUTO_START_ON_LAUNCH", "1") == "1"
UI_THEME = os.getenv("UI_THEME", "auto").strip().lower()
UI_TRANSCRIBE_MODE = os.getenv("UI_TRANSCRIBE_MODE", "realtime").strip().lower()
WINDOW_TOP_RIGHT = os.getenv("WINDOW_TOP_RIGHT", "1") == "1"
STOP_FORCE_KILL_MS = int(os.getenv("STOP_FORCE_KILL_MS", "1200"))
CHUNK_SECONDS_CHUNKED = int(os.getenv("CHUNK_SECONDS_CHUNKED", os.getenv("CHUNK_SECONDS", "10")))


class RealtimeUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Whspr Realtime")
        self.root.geometry("440x320")
        self.root.minsize(400, 260)

        self.proc: subprocess.Popen | None = None
        self.stop_requested = False
        self.status_var = tk.StringVar(value="Idle")
        if UI_TRANSCRIBE_MODE == "chunked":
            initial_mode = "Chunked"
        else:
            initial_mode = "Realtime"
        self.mode_var = tk.StringVar(value=initial_mode)
        self.session_anchor_ts = time.time()
        self.active_transcript_file: Path | None = None
        self._last_view_content: str | None = None
        self.current_chunk_seconds = CHUNK_SECONDS_CHUNKED

        self.theme_mode = self._resolve_theme_mode()
        self.colors = self._theme_tokens(self.theme_mode)

        self._apply_platform_style()

        outer = ttk.Frame(root, padding=(10, 10, 10, 10), style="Root.TFrame")
        outer.pack(fill="both", expand=True)

        controls = ttk.Frame(outer, style="Card.TFrame", padding=(10, 8))
        controls.pack(fill="x")

        self.toggle_btn = ttk.Button(
            controls,
            text="Record",
            command=self.toggle_transcription,
            style="Action.TButton",
        )
        self.toggle_btn.pack(side="left")

        self.mode_combo = ttk.Combobox(
            controls,
            textvariable=self.mode_var,
            values=("Realtime", "Chunked"),
            state="readonly",
            width=10,
        )
        self.mode_combo.pack(side="left", padx=(8, 0))
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_changed)

        self.status_badge = tk.Label(
            controls,
            text="IDLE",
            padx=7,
            pady=2,
            font=("SF Pro Text", 9, "bold"),
            borderwidth=1,
            relief="flat",
        )
        self.status_badge.pack(side="left", padx=(10, 0))

        transcript_card = ttk.Frame(outer, style="Card.TFrame", padding=(2, 2))
        transcript_card.pack(fill="both", expand=True)

        self.text = tk.Text(
            transcript_card,
            wrap="word",
            font=("SF Mono", 10),
            relief="flat",
            borderwidth=0,
            padx=8,
            pady=6,
        )
        self.text.pack(side="left", fill="both", expand=True)
        self.text.configure(
            bg=self.colors["text_bg"],
            fg=self.colors["text_fg"],
            insertbackground=self.colors["text_fg"],
            selectbackground=self.colors["selection_bg"],
            selectforeground=self.colors["selection_fg"],
        )

        scrollbar = ttk.Scrollbar(transcript_card, orient="vertical", command=self.text.yview)
        scrollbar.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scrollbar.set)
        self.set_transcript_view("Waiting for transcript...\n")

        self._set_status("Idle")
        self._update_toggle_button()

        self.root.bind("<Command-Return>", lambda _event: self.toggle_transcription())
        self.root.bind("<Command-period>", lambda _event: self.stop_transcription())
        self.root.bind("<Command-q>", lambda _event: self.on_close())

        if WINDOW_TOP_RIGHT:
            self._position_top_right()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.schedule_refresh()
        if AUTO_START_ON_LAUNCH:
            self.root.after(250, self.start_transcription)

    def _position_top_right(self):
        # Place window near top-right with a small inset margin.
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        screen_w = self.root.winfo_screenwidth()
        x = max(0, screen_w - width - 20)
        y = 24
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def _resolve_theme_mode(self) -> str:
        if UI_THEME in {"light", "dark"}:
            return UI_THEME
        if platform.system() != "Darwin":
            return "light"
        try:
            out = subprocess.check_output(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            return "dark" if out.lower() == "dark" else "light"
        except Exception:
            return "light"

    def _theme_tokens(self, mode: str) -> dict[str, str]:
        if mode == "dark":
            return {
                "root_bg": "#191919",
                "card_bg": "#202020",
                "text_bg": "#232323",
                "text_fg": "#e9e9e7",
                "muted_fg": "#a3a3a0",
                "selection_bg": "#3b3b3b",
                "selection_fg": "#f5f5f4",
            }
        return {
            "root_bg": "#f7f6f3",
            "card_bg": "#ffffff",
            "text_bg": "#fbfbfa",
            "text_fg": "#37352f",
            "muted_fg": "#787774",
            "selection_bg": "#e9e8e5",
            "selection_fg": "#2f2f2d",
        }

    def _apply_platform_style(self):
        style = ttk.Style(self.root)
        if platform.system() == "Darwin":
            try:
                style.theme_use("aqua")
            except tk.TclError:
                pass

        self.root.configure(background=self.colors["root_bg"])
        style.configure("Root.TFrame", background=self.colors["root_bg"])
        style.configure("Card.TFrame", background=self.colors["card_bg"])
        style.configure(
            "Meta.TLabel",
            font=("SF Pro Text", 10),
            foreground=self.colors["muted_fg"],
            background=self.colors["root_bg"],
        )
        style.configure(
            "Status.TLabel",
            font=("SF Pro Text", 10),
            foreground=self.colors["muted_fg"],
            background=self.colors["card_bg"],
        )
        style.configure("Action.TButton", font=("SF Pro Text", 11))

    def _set_status(self, status: str):
        self.status_var.set(status)
        dark = self.theme_mode == "dark"
        if status == "Connected / Listening":
            self.status_badge.configure(
                text="LISTENING",
                bg="#24432b" if dark else "#d8f4dc",
                fg="#adf3bc" if dark else "#0f6a2b",
            )
        elif status == "Transcribing Chunks":
            self.status_badge.configure(
                text="TRANSCRIBING",
                bg="#24432b" if dark else "#d8f4dc",
                fg="#adf3bc" if dark else "#0f6a2b",
            )
        elif status == "Connecting...":
            self.status_badge.configure(
                text="CONNECTING",
                bg="#22314a" if dark else "#d9e8ff",
                fg="#a8c6ff" if dark else "#1f4f99",
            )
        elif status == "Starting...":
            self.status_badge.configure(
                text="STARTING",
                bg="#22314a" if dark else "#d9e8ff",
                fg="#a8c6ff" if dark else "#1f4f99",
            )
        elif status == "Stopping...":
            self.status_badge.configure(
                text="STOPPING",
                bg="#4b4125" if dark else "#fff2cc",
                fg="#f2d792" if dark else "#7a5c00",
            )
        elif status.startswith("Error") or status == "Stop failed":
            self.status_badge.configure(
                text="ERROR",
                bg="#4a2626" if dark else "#fde2e2",
                fg="#ffb2b2" if dark else "#8f1d1d",
            )
        else:
            self.status_badge.configure(
                text="IDLE",
                bg="#2d2d2d" if dark else "#ecebe8",
                fg="#b8b8b5" if dark else "#5b5a56",
            )
        self._update_toggle_button()

    def _is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _update_toggle_button(self):
        if self._is_running() or self.status_var.get() in {"Connecting...", "Starting...", "Stopping..."}:
            self.toggle_btn.configure(text="Stop")
            self.mode_combo.configure(state="disabled")
        else:
            self.toggle_btn.configure(text="Record")
            self.mode_combo.configure(state="readonly")

    def _mode_key(self) -> str:
        mode = self.mode_var.get()
        if mode == "Chunked":
            return "chunked"
        return "realtime"

    def _current_backend_script(self) -> Path:
        return CHUNKED_SCRIPT if self._mode_key() == "chunked" else REALTIME_SCRIPT

    def _current_session_pattern(self) -> str:
        return "chunked_session_*.txt" if self._mode_key() == "chunked" else "realtime_session_*.txt"

    def _kill_chunked_processes(self):
        # Extra safety: chunked recording can block in audio reads on some systems.
        # This kills any lingering chunked pipeline processes started from the UI.
        try:
            subprocess.run(
                ["pkill", "-f", "chunked_transcribe.py"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception:
            pass

    def _on_mode_changed(self, _event=None):
        if self._is_running():
            return
        self.session_anchor_ts = time.time()
        self.active_transcript_file = None
        self.set_transcript_view("Waiting for transcript...\n")

    def set_transcript_view(self, content: str):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.see("end")
        self.text.configure(state="disabled")

    def _find_latest_file(self, patterns: list[str], min_mtime: float | None = None) -> Path | None:
        candidates: list[Path] = []
        for pattern in patterns:
            for p in AUDIO_LOGS_DIR.glob(pattern):
                try:
                    if min_mtime is None or p.stat().st_mtime >= min_mtime:
                        candidates.append(p)
                except OSError:
                    continue

        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)

    def latest_session_file(self) -> Path | None:
        if not AUDIO_LOGS_DIR.exists():
            return None

        # Always rescan so we can switch to newer files created after startup.
        selected_latest = self._find_latest_file(
            [self._current_session_pattern()], min_mtime=self.session_anchor_ts
        )
        selected_any = self._find_latest_file([self._current_session_pattern()])
        any_latest = self._find_latest_file(["chunked_session_*.txt", "realtime_session_*.txt"])

        candidate = selected_latest or selected_any or any_latest
        if candidate is None:
            return None

        try:
            candidate_mtime = candidate.stat().st_mtime
        except OSError:
            return self.active_transcript_file

        if self.active_transcript_file is None:
            self.active_transcript_file = candidate
            return self.active_transcript_file

        try:
            active_mtime = self.active_transcript_file.stat().st_mtime
        except OSError:
            self.active_transcript_file = candidate
            return self.active_transcript_file

        if candidate_mtime >= active_mtime:
            self.active_transcript_file = candidate

        return self.active_transcript_file

    def refresh_transcript(self):
        transcript_file = self.latest_session_file()
        if transcript_file is None:
            rendered = "Waiting for transcript...\n"
            if rendered != self._last_view_content:
                self.set_transcript_view(rendered)
                self._last_view_content = rendered
            return

        try:
            content = transcript_file.read_text(encoding="utf-8")
            if len(content) > MAX_VIEW_CHARS:
                content = content[-MAX_VIEW_CHARS:]
            rendered = content if content else "(empty transcript)\n"
            if rendered != self._last_view_content:
                self.set_transcript_view(rendered)
                self._last_view_content = rendered
        except Exception as exc:
            rendered = f"Error reading transcript: {exc}\n"
            if rendered != self._last_view_content:
                self.set_transcript_view(rendered)
                self._last_view_content = rendered

    def schedule_refresh(self):
        try:
            self.refresh_transcript()
        except Exception as exc:
            # Never let the refresh loop die on transient file/process races.
            rendered = f"Refresh error: {exc}\n"
            if rendered != self._last_view_content:
                self.set_transcript_view(rendered)
                self._last_view_content = rendered
        finally:
            self.root.after(REFRESH_MS, self.schedule_refresh)

    def toggle_transcription(self):
        if self._is_running() or self.status_var.get() in {"Connecting...", "Starting..."}:
            self.stop_transcription()
        else:
            self.start_transcription()

    def start_transcription(self):
        if self._is_running():
            if self._mode_key() == "chunked":
                self._set_status("Transcribing Chunks")
            else:
                self._set_status("Connected / Listening")
            return

        if not os.getenv("OPENAI_API_KEY", "").strip():
            self._set_status("Error: OPENAI_API_KEY missing")
            self.set_transcript_view("OPENAI_API_KEY missing in environment or .env\n")
            return

        backend_script = self._current_backend_script()
        if not backend_script.exists():
            self._set_status("Error: backend script missing")
            return

        # Start in a process group so we can stop child processes cleanly.
        # Reset transcript source anchor so each run starts with a fresh UI session view.
        self.stop_requested = False
        self.session_anchor_ts = time.time()
        self.active_transcript_file = None
        self.set_transcript_view("Waiting for transcript...\n")

        if self._mode_key() == "chunked":
            self._set_status("Starting...")
            self.current_chunk_seconds = CHUNK_SECONDS_CHUNKED
            self.set_transcript_view(
                f"Starting chunked transcription...\n"
                f"Recording first chunk (~{self.current_chunk_seconds}s), then sending to API.\n"
                "Transcript will appear after the first chunk completes.\n"
            )
        else:
            self._set_status("Connecting...")
            self.current_chunk_seconds = 0

        proc_env = os.environ.copy()
        if self._mode_key() == "chunked":
            proc_env["OPENAI_TRANSCRIBE_MODEL"] = "gpt-4o-mini-transcribe"
            proc_env["CHUNK_SECONDS"] = str(CHUNK_SECONDS_CHUNKED)

        self.proc = subprocess.Popen(
            [sys.executable, str(backend_script)],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=proc_env,
            cwd=str(PROJECT_DIR),
        )
        self.root.after(1200, self._verify_backend_started)

    def _verify_backend_started(self):
        if not self.proc:
            return
        code = self.proc.poll()
        if code is not None:
            self._set_status(f"Error: backend exited ({code})")
            script_name = self._current_backend_script().name
            self.set_transcript_view(
                f"Backend exited quickly. Run {script_name} in Terminal for details.\n"
            )
        else:
            if self.stop_requested:
                self.stop_transcription()
                return
            if self._mode_key() == "chunked":
                self._set_status("Transcribing Chunks")
            else:
                self._set_status("Connected / Listening")

    def stop_transcription(self):
        if self.status_var.get() in {"Connecting...", "Starting..."}:
            self.stop_requested = True
            if self._mode_key() == "chunked":
                self._kill_chunked_processes()
            self._set_status("Stopping...")
            self.root.after(150, self._verify_backend_stopped)
            self.root.after(STOP_FORCE_KILL_MS, self._force_kill_if_needed)
            return

        if not self._is_running():
            self._set_status("Idle")
            return

        try:
            proc = self.proc
            if proc is None:
                self._set_status("Idle")
                return
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
            if self._mode_key() == "chunked":
                self._kill_chunked_processes()
            self._set_status("Stopping...")
            self.root.after(350, self._verify_backend_stopped)
            self.root.after(STOP_FORCE_KILL_MS, self._force_kill_if_needed)
        except Exception:
            self._set_status("Stop failed")

    def _verify_backend_stopped(self):
        if not self._is_running():
            self._set_status("Idle")
        else:
            self.root.after(350, self._verify_backend_stopped)

    def _force_kill_if_needed(self):
        if self._mode_key() == "chunked":
            self._kill_chunked_processes()
        if not self._is_running():
            return
        try:
            proc = self.proc
            if proc is None:
                self._set_status("Idle")
                return
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                proc.kill()
            self._set_status("Idle")
        except Exception:
            self._set_status("Stop failed")

    def on_close(self):
        self.stop_transcription()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = RealtimeUI(root)
    app._set_status("Idle")
    root.mainloop()


if __name__ == "__main__":
    main()
