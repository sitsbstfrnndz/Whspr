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
DIARIZATION_ENABLED = os.getenv("DIARIZATION", "0") == "1"
DIARIZATION_SPEAKERS = max(1, int(os.getenv("DIARIZATION_SPEAKERS", "2")))

LOG_DIR = Path(os.path.expanduser(os.getenv("TRANSCRIPT_DIR", "~/AudioLogs")))

running = True


def stop_handler(signum, frame):
    del signum, frame
    global running
    running = False


def ensure_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


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


def append_text_line(transcript_file: Path, text: str):
    with transcript_file.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def extract_chunk_features(audio: np.ndarray) -> np.ndarray:
    # Lightweight voice signature for rough clustering per chunk.
    x = audio.astype(np.float32)
    if x.size == 0:
        return np.zeros(4, dtype=np.float32)

    rms = float(np.sqrt(np.mean(np.square(x))) + 1e-12)
    zcr = float(np.mean(np.abs(np.diff(np.signbit(x)))))

    spectrum = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / SAMPLE_RATE)
    spec_sum = float(np.sum(spectrum) + 1e-12)
    centroid = float(np.sum(freqs * spectrum) / spec_sum)

    bandwidth = float(np.sqrt(np.sum(((freqs - centroid) ** 2) * spectrum) / spec_sum))

    return np.array([np.log(rms), zcr, centroid / 4000.0, bandwidth / 4000.0], dtype=np.float32)


def assign_speaker(
    feature: np.ndarray,
    centroids: list[np.ndarray],
    counts: list[int],
    max_speakers: int,
) -> int:
    if not centroids:
        centroids.append(feature.copy())
        counts.append(1)
        return 1

    distances = [float(np.linalg.norm(feature - c)) for c in centroids]
    best_idx = int(np.argmin(distances))

    # Spawn a new speaker if sufficiently different and we still can.
    if distances[best_idx] > 0.35 and len(centroids) < max_speakers:
        centroids.append(feature.copy())
        counts.append(1)
        return len(centroids)

    n = counts[best_idx]
    centroids[best_idx] = (centroids[best_idx] * n + feature) / (n + 1)
    counts[best_idx] = n + 1
    return best_idx + 1


def append_chunk_as_sentences(
    transcript_file: Path,
    chunk_text: str,
    speaker_label: str | None,
    state: dict,
):
    cleaned = " ".join(chunk_text.split())

    # For silent chunks, write a plain blank line as a separator.
    if not cleaned:
        append_text_line(transcript_file, "")
        state["last_speaker"] = None
        return

    spacer = ""
    if transcript_file.exists() and transcript_file.stat().st_size > 0:
        with transcript_file.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            last_char = f.read(1).decode("utf-8", errors="ignore")
        if last_char not in {" ", "\n"}:
            spacer = " "

    with transcript_file.open("a", encoding="utf-8") as f:
        last_speaker = state.get("last_speaker")
        if speaker_label and speaker_label != last_speaker:
            if transcript_file.stat().st_size > 0 and last_char != "\n":
                f.write("\n")
            f.write(f"[{speaker_label}] ")
            spacer = ""
            state["last_speaker"] = speaker_label

        f.write(spacer + cleaned)
        if cleaned.endswith((".", "!", "?")):
            f.write("\n")


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
    if DIARIZATION_ENABLED:
        print(f"Diarization: on ({DIARIZATION_SPEAKERS} speakers)")
    else:
        print("Diarization: off")
    print(f"Transcript file: {transcript_file}")

    idx = 0
    centroids: list[np.ndarray] = []
    counts: list[int] = []
    transcript_state = {"last_speaker": None}

    while running:
        idx += 1
        chunk_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        wav_path = LOG_DIR / f"chunk_{session_stamp}_{idx:04d}_{chunk_stamp}.wav"

        try:
            audio = record_chunk()
            sf.write(wav_path, audio, SAMPLE_RATE, subtype="PCM_16")

            text = transcribe_chunk(client, wav_path)
            speaker_label = None
            if DIARIZATION_ENABLED and text.strip():
                feature = extract_chunk_features(audio)
                speaker_id = assign_speaker(feature, centroids, counts, DIARIZATION_SPEAKERS)
                speaker_label = f"Speaker {speaker_id}"

            append_chunk_as_sentences(transcript_file, text, speaker_label, transcript_state)
            if text:
                if speaker_label:
                    print(f"[{speaker_label}] {text}")
                else:
                    print(text)
            else:
                print("")

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
