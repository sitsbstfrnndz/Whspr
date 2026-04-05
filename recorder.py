import os
import time
import signal
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

OUTPUT_DIR = os.path.expanduser("~/AudioLogs")
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_SECONDS = 10
SILENCE_THRESHOLD = 0.002
MIN_VOICE_SECONDS = 1.5

running = True


def stop_handler(signum, frame):
    global running
    running = False


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def has_voice(audio, sr, threshold, min_voice_seconds):
    window = int(sr * 0.05)
    if window <= 0:
        return True
    voiced = 0
    for i in range(0, len(audio), window):
        seg = audio[i:i + window]
        if len(seg) == 0:
            continue
        rms = np.sqrt(np.mean(seg ** 2))
        if rms > threshold:
            voiced += len(seg)
    return (voiced / sr) >= min_voice_seconds


def record_loop():
    ensure_dir(OUTPUT_DIR)
    start_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(OUTPUT_DIR, f"rec_{start_ts}.wav")
    frames_per_chunk = int(SAMPLE_RATE * CHUNK_SECONDS)
    collected = []

    print("Recording started. Press Ctrl+C to stop.")
    print("Saving to:", filename)

    try:
        while running:
            audio = sd.rec(
                frames_per_chunk,
                samplerate=SAMPLE_RATE,
                channels=CHANNELS,
                dtype="float32",
            )
            sd.wait()
            mono = audio[:, 0] if audio.ndim > 1 else audio
            collected.append(mono)
    except Exception as e:
        print("Record error:", e)
        time.sleep(1)

    if not collected:
        print("No audio captured.")
        print("Stopped.")
        return

    full_audio = np.concatenate(collected)
    if has_voice(full_audio, SAMPLE_RATE, SILENCE_THRESHOLD, MIN_VOICE_SECONDS):
        sf.write(filename, full_audio, SAMPLE_RATE, subtype="PCM_16")
        print("Saved:", filename)
    else:
        print("Recording was mostly silent. File not saved.")

    print("Stopped.")


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    record_loop()
