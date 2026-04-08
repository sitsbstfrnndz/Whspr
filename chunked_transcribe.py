import os
import signal
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import sounddevice as sd
import soundfile as sf
from openai import OpenAI


def load_dotenv():
    try:
        dotenv_module = __import__("dotenv")
        return getattr(dotenv_module, "load_dotenv")()
    except Exception:
        return False


load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
CHUNK_SECONDS = int(os.getenv("CHUNK_SECONDS", "4"))
SAMPLE_RATE = int(os.getenv("CHUNK_SAMPLE_RATE", "16000"))
CHANNELS = 1
SAVE_CHUNKS = os.getenv("SAVE_CHUNKS", "0") == "1"

LOG_DIR = Path(os.path.expanduser(os.getenv("TRANSCRIPT_DIR", "~/AudioLogs")))

running = True


def stop_handler(signum, frame):
    del signum, frame
    global running
    running = False


def ensure_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def record_chunk() -> np.ndarray:
    frames_total = int(SAMPLE_RATE * CHUNK_SECONDS)
    read_block = max(1, SAMPLE_RATE // 10)  # 100ms blocks for responsive stop.
    parts: list[np.ndarray] = []

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        remaining = frames_total
        while remaining > 0 and running:
            take = min(read_block, remaining)
            frames, _overflowed = stream.read(take)
            mono = frames[:, 0] if frames.ndim > 1 else frames
            parts.append(np.asarray(mono, dtype=np.float32))
            remaining -= take

    if not parts:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(parts, axis=0)


def transcribe_chunk(client: OpenAI, wav_path: Path) -> str:
    with wav_path.open("rb") as f:
        text = client.audio.transcriptions.create(
            model=MODEL,
            file=f,
            response_format="text",
        )
    return str(text).strip()


def append_text_line(transcript_file: Path, text: str):
    with transcript_file.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def append_chunk_as_sentences(transcript_file: Path, chunk_text: str):
    cleaned = " ".join(chunk_text.split())

    # For silent chunks, write a plain blank line as a separator.
    if not cleaned:
        append_text_line(transcript_file, "")
        return

    spacer = ""
    if transcript_file.exists() and transcript_file.stat().st_size > 0:
        with transcript_file.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            last_char = f.read(1).decode("utf-8", errors="ignore")
        if last_char not in {" ", "\n"}:
            spacer = " "

    with transcript_file.open("a", encoding="utf-8") as f:
        f.write(spacer + cleaned)


def main():
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    ensure_dirs()
    client = OpenAI(api_key=API_KEY)

    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript_file = LOG_DIR / f"chunked_session_{session_stamp}.txt"

    print("Chunked transcription started. Press Ctrl+C to stop.")
    print(f"Model: {MODEL}")
    print(f"Chunk length: {CHUNK_SECONDS}s")
    print(f"Transcript file: {transcript_file}")

    idx = 0
    while running:
        idx += 1
        chunk_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = LOG_DIR / f"chunk_{session_stamp}_{idx:04d}_{chunk_stamp}.wav"

        try:
            audio = record_chunk()
            if audio.size == 0:
                append_text_line(transcript_file, "")
                print("")
                continue

            sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")

            text = transcribe_chunk(client, wav_path)
            append_chunk_as_sentences(transcript_file, text)
            print(text if text else "")

            if not SAVE_CHUNKS:
                try:
                    wav_path.unlink(missing_ok=True)
                except Exception:
                    pass

        except Exception as exc:
            print(f"Chunk {idx:04d} error: {exc}")
            time.sleep(0.5)

    print(f"Stopped. Transcript saved: {transcript_file}")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"\nStartup/runtime error: {exc}")
