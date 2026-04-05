import os
import signal
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import ttk

AUDIO_LOGS_DIR = Path(os.path.expanduser("~/AudioLogs"))
START_SCRIPT = Path(os.path.expanduser("~/AudioRecorder/start_chunked_transcribe.command"))
REFRESH_MS = 1000
MAX_CHARS = 12000


class LiveTranscriptApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Live Transcript")
        self.root.geometry("900x560")
        self.proc: subprocess.Popen | None = None

        self.status_var = tk.StringVar(value="Idle")
        self.file_var = tk.StringVar(value="Transcript file: (waiting)")

        container = ttk.Frame(root, padding=12)
        container.pack(fill="both", expand=True)

        top = ttk.Frame(container)
        top.pack(fill="x")

        self.start_btn = ttk.Button(top, text="Start", command=self.start_transcription)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(top, text="Stop", command=self.stop_transcription)
        self.stop_btn.pack(side="left", padx=(8, 0))

        ttk.Label(top, textvariable=self.status_var).pack(side="left", padx=(16, 0))

        ttk.Label(container, textvariable=self.file_var).pack(anchor="w", pady=(10, 6))

        self.text = tk.Text(container, wrap="word", font=("Menlo", 13))
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", "Live transcript will appear here...\n")
        self.text.configure(state="disabled")

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.schedule_refresh()

    def set_text(self, content: str):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.text.see("end")
        self.text.configure(state="disabled")

    def latest_session_file(self) -> Path | None:
        if not AUDIO_LOGS_DIR.exists():
            return None
        files = sorted(AUDIO_LOGS_DIR.glob("session_*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def refresh_transcript(self):
        session_file = self.latest_session_file()
        if session_file is None:
            self.file_var.set("Transcript file: (none yet)")
            return

        self.file_var.set(f"Transcript file: {session_file}")

        try:
            content = session_file.read_text(encoding="utf-8")
            if len(content) > MAX_CHARS:
                content = content[-MAX_CHARS:]
            self.set_text(content if content else "(empty transcript)")
        except Exception as exc:
            self.set_text(f"Error reading transcript: {exc}\n")

    def schedule_refresh(self):
        self.refresh_transcript()
        self.root.after(REFRESH_MS, self.schedule_refresh)

    def start_transcription(self):
        if self.proc and self.proc.poll() is None:
            self.status_var.set("Running")
            return

        if not START_SCRIPT.exists():
            self.status_var.set("Error: start script missing")
            return

        # Run the chunked transcriber in the background process group.
        self.proc = subprocess.Popen(
            ["bash", str(START_SCRIPT)],
            preexec_fn=os.setsid,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.status_var.set("Running")

    def stop_transcription(self):
        if not self.proc or self.proc.poll() is not None:
            self.status_var.set("Idle")
            return

        try:
            os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            self.status_var.set("Stopping...")
        except Exception:
            self.status_var.set("Stop failed")

    def on_close(self):
        self.stop_transcription()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = LiveTranscriptApp(root)
    app.status_var.set("Idle")
    root.mainloop()


if __name__ == "__main__":
    main()
