import os
import signal
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from openai import OpenAI

SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "4"))
MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")

AUDIO_DIR = Path(os.path.expanduser("~/AudioLogs"))
TRANSCRIPT_DIR = Path(os.path.expanduser("~/AudioLogs"))

running = True


def stop_handler(signum, frame):
    global running
    running = False


def ensure_dirs():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)


def record_chunk() -> np.ndarray:
    frames = int(SAMPLE_RATE * CHUNK_SECONDS)
    audio = sd.rec(frames, samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32")
    sd.wait()
    mono = audio[:, 0] if audio.ndim > 1 else audio
    return mono


def transcribe_chunk(client: OpenAI, wav_path: Path) -> str:
    with wav_path.open("rb") as f:
        text = client.audio.transcriptions.create(
            model=MODEL,
            file=f,
            response_format="text",
        )
    return str(text).strip()


def append_transcript(transcript_file: Path, idx: int, start_ts: str, text: str):
    with transcript_file.open("a", encoding="utf-8") as f:
        f.write(f"[{idx:04d}] {start_ts}\n")
        f.write(text + "\n\n")


def main():
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    ensure_dirs()
    client = OpenAI()

    session_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript_file = TRANSCRIPT_DIR / f"session_{session_ts}.txt"

    print("Chunked transcription started. Press Ctrl+C to stop.")
    print(f"Chunk length: {CHUNK_SECONDS}s")
    print(f"Model: {MODEL}")
    print(f"Transcript file: {transcript_file}")

    idx = 0
    while running:
        idx += 1
        chunk_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = AUDIO_DIR / f"chunk_{session_ts}_{idx:04d}_{chunk_ts}.wav"

        try:
            audio = record_chunk()
            sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")
            print(f"Saved chunk: {wav_path.name}")

            text = transcribe_chunk(client, wav_path)
            if not text:
                text = "[no speech detected]"
            append_transcript(transcript_file, idx, chunk_ts, text)
            print(f"Transcript[{idx:04d}]: {text}")

        except Exception as exc:
            print(f"Chunk {idx:04d} error: {exc}")
            time.sleep(1)

    print("Stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    main()
