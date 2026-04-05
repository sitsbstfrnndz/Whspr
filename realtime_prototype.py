import asyncio
import base64
import json
import os
import signal
import wave
from collections import deque
from datetime import datetime
from time import monotonic

import numpy as np
import sounddevice as sd
import websockets
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - fallback when python-dotenv isn't installed
    def load_dotenv():
        return False

load_dotenv()

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
TRANSCRIBE_LANG = os.getenv("OPENAI_TRANSCRIBE_LANGUAGE", "en")
TRANSCRIBE_PROMPT = os.getenv("OPENAI_TRANSCRIBE_PROMPT", "")
DEBUG_EVENTS = os.getenv("OPENAI_REALTIME_DEBUG", "0") == "1"
SAVE_AUDIO = os.getenv("SAVE_AUDIO", "0") == "1"
SAVE_AUDIO_DIR = os.path.expanduser(os.getenv("SAVE_AUDIO_DIR", "~/AudioLogs"))
STABILIZE_PARTIALS = os.getenv("STABILIZE_PARTIALS", "1") == "1"
POST_PROCESS_FINAL = os.getenv("POST_PROCESS_FINAL", "1") == "1"
WRITE_GLOBAL_TRANSCRIPT = os.getenv("WRITE_GLOBAL_TRANSCRIPT", "1") == "1"

VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.5"))
VAD_PREFIX_MS = int(os.getenv("VAD_PREFIX_PADDING_MS", "300"))
VAD_SILENCE_MS = int(os.getenv("VAD_SILENCE_MS", "500"))

METRICS_INTERVAL_SEC = float(os.getenv("METRICS_INTERVAL_SEC", "5"))
RECENT_FINALS_MAX = int(os.getenv("RECENT_FINALS_MAX", "20"))

SAMPLE_RATE = 24000
CHANNELS = 1
FRAMES_PER_CHUNK = 4800  # 200ms at 24kHz
TRANSCRIPT_DIR = os.path.expanduser(os.getenv("TRANSCRIPT_DIR", "~/AudioLogs"))
GLOBAL_TRANSCRIPT_FILE = os.path.join(
    TRANSCRIPT_DIR,
    os.getenv("GLOBAL_TRANSCRIPT_FILENAME", "realtime_transcript.txt"),
)

running = True


def stop_handler(signum, frame):
    global running
    running = False


def float_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)
    return pcm16.tobytes()


def merge_with_overlap(existing: str, new_text: str) -> str:
    """Merge text chunks while removing repeated overlap at the boundary."""
    if not new_text:
        return existing
    if not existing:
        return new_text

    if new_text in existing:
        return existing

    max_overlap = min(len(existing), len(new_text))
    for size in range(max_overlap, 0, -1):
        if existing[-size:] == new_text[:size]:
            return existing + new_text[size:]

    return existing + new_text


def normalize_for_dedup(text: str) -> str:
    compact = " ".join(text.lower().strip().split())
    return "".join(ch for ch in compact if ch.isalnum() or ch.isspace())


def maybe_post_process(text: str) -> str:
    cleaned = " ".join(text.strip().split())
    if not POST_PROCESS_FINAL or not cleaned:
        return cleaned

    if cleaned[0].isalpha():
        cleaned = cleaned[0].upper() + cleaned[1:]

    if cleaned[-1].isalnum():
        cleaned += "."
    return cleaned


def stable_prefix_for_streaming(new_text: str) -> str:
    """Only emit up to a stable boundary to reduce partial-word flicker."""
    if not new_text:
        return ""

    boundary = max(
        new_text.rfind(" "),
        new_text.rfind("."),
        new_text.rfind(","),
        new_text.rfind("!"),
        new_text.rfind("?"),
    )
    if boundary < 0:
        return ""
    return new_text[: boundary + 1]


def is_duplicate_final(candidate: str, recent_norm: deque[str]) -> bool:
    norm = normalize_for_dedup(candidate)
    if not norm:
        return True
    for prev in recent_norm:
        if norm == prev:
            return True
        # Also suppress very similar partial repeats.
        if len(norm) > 20 and (norm in prev or prev in norm):
            return True
    return False


async def send_audio(ws, stats):
    sent_chunks = 0
    recorded_audio = bytearray()
    audio_file = ""

    if SAVE_AUDIO:
        os.makedirs(SAVE_AUDIO_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        audio_file = os.path.join(SAVE_AUDIO_DIR, f"realtime_session_{stamp}.wav")

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        print("Microphone stream opened.", flush=True)
        if SAVE_AUDIO:
            print(f"Audio recording enabled. Output file: {audio_file}", flush=True)

        while running:
            # stream.read is blocking; run it in a thread to keep asyncio responsive.
            frames, overflowed = await asyncio.to_thread(stream.read, FRAMES_PER_CHUNK)
            mono = frames[:, 0] if frames.ndim > 1 else frames
            pcm16_bytes = float_to_pcm16_bytes(mono)
            payload = base64.b64encode(pcm16_bytes).decode("ascii")

            if overflowed:
                stats["input_overflows"] += 1

            if SAVE_AUDIO:
                recorded_audio.extend(pcm16_bytes)

            await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": payload}))
            sent_chunks += 1
            stats["sent_chunks"] += 1
            stats["audio_seconds_sent"] += len(mono) / SAMPLE_RATE
            stats["last_audio_send_ts"] = monotonic()
            if stats["first_audio_send_ts"] is None:
                stats["first_audio_send_ts"] = stats["last_audio_send_ts"]

            if DEBUG_EVENTS and sent_chunks % 20 == 0:
                print(f"[debug] sent_chunks={sent_chunks}", flush=True)

            await asyncio.sleep(0)

    if SAVE_AUDIO and recorded_audio:
        with wave.open(audio_file, "wb") as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(2)  # PCM16
            wav_file.setframerate(SAMPLE_RATE)
            wav_file.writeframes(bytes(recorded_audio))
        print(f"Saved audio recording to: {audio_file}", flush=True)


def append_transcript_line(file_path: str, line: str):
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def receive_events(ws, stats, session_transcript_file: str, global_transcript_file: str):
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    live_text_by_item = {}
    emitted_text_by_item = {}
    recent_norm = deque(maxlen=max(1, RECENT_FINALS_MAX))

    while running:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        event = json.loads(raw)
        event_type = event.get("type", "")

        if DEBUG_EVENTS:
            print(f"\n[event] {event_type}", flush=True)

        if event_type == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if delta:
                stats["delta_events"] += 1
                stats["last_transcript_event_ts"] = monotonic()
                if stats["first_transcript_event_ts"] is None:
                    stats["first_transcript_event_ts"] = stats["last_transcript_event_ts"]

                item_id = event.get("item_id", "")
                previous_text = live_text_by_item.get(item_id, "")
                merged_text = merge_with_overlap(previous_text, delta)
                live_text_by_item[item_id] = merged_text

                if STABILIZE_PARTIALS:
                    emitted = emitted_text_by_item.get(item_id, "")
                    if merged_text.startswith(emitted):
                        candidate = merged_text[len(emitted) :]
                        stable = stable_prefix_for_streaming(candidate)
                        if stable:
                            print(stable, end="", flush=True)
                            emitted_text_by_item[item_id] = emitted + stable
                else:
                    new_fragment = merged_text[len(previous_text) :]
                    if new_fragment:
                        print(new_fragment, end="", flush=True)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            if transcript:
                stats["completed_events"] += 1
                stats["last_transcript_event_ts"] = monotonic()

                item_id = event.get("item_id", "")
                if STABILIZE_PARTIALS and item_id in live_text_by_item:
                    emitted = emitted_text_by_item.get(item_id, "")
                    merged_text = live_text_by_item[item_id]
                    if merged_text.startswith(emitted):
                        remainder = merged_text[len(emitted) :]
                        if remainder:
                            print(remainder, end="", flush=True)

                print("", flush=True)

                final_text = maybe_post_process(transcript)
                if final_text and not is_duplicate_final(final_text, recent_norm):
                    append_transcript_line(session_transcript_file, final_text)
                    if WRITE_GLOBAL_TRANSCRIPT:
                        append_transcript_line(global_transcript_file, final_text)

                    recent_norm.append(normalize_for_dedup(final_text))

                if item_id in live_text_by_item:
                    del live_text_by_item[item_id]
                if item_id in emitted_text_by_item:
                    del emitted_text_by_item[item_id]

        elif event_type == "error":
            stats["error_events"] += 1
            print("\nRealtime API error:", event.get("error", event), flush=True)


async def metrics_reporter(stats):
    while running:
        await asyncio.sleep(max(1.0, METRICS_INTERVAL_SEC))

        now = monotonic()
        uptime = now - stats["start_ts"]
        first_latency = "n/a"
        if stats["first_audio_send_ts"] is not None and stats["first_transcript_event_ts"] is not None:
            first_latency_val = stats["first_transcript_event_ts"] - stats["first_audio_send_ts"]
            first_latency = f"{first_latency_val:.2f}s"

        live_gap = "n/a"
        if stats["last_transcript_event_ts"] is not None:
            live_gap = f"{(now - stats['last_transcript_event_ts']):.2f}s"

        print(
            "[metrics] "
            f"uptime={uptime:.1f}s "
            f"chunks={stats['sent_chunks']} "
            f"audio={stats['audio_seconds_sent']:.1f}s "
            f"delta={stats['delta_events']} "
            f"completed={stats['completed_events']} "
            f"overflows={stats['input_overflows']} "
            f"errors={stats['error_events']} "
            f"first_latency={first_latency} "
            f"last_event_gap={live_gap}",
            flush=True,
        )


async def main():
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    url = f"wss://api.openai.com/v1/realtime?model={MODEL}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    stats = {
        "start_ts": monotonic(),
        "sent_chunks": 0,
        "audio_seconds_sent": 0.0,
        "delta_events": 0,
        "completed_events": 0,
        "error_events": 0,
        "input_overflows": 0,
        "first_audio_send_ts": None,
        "last_audio_send_ts": None,
        "first_transcript_event_ts": None,
        "last_transcript_event_ts": None,
    }

    session_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_transcript_file = os.path.join(TRANSCRIPT_DIR, f"realtime_session_{session_stamp}.txt")

    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    # Ensure files exist but keep transcript content plain (no metadata headers).
    open(session_transcript_file, "a", encoding="utf-8").close()
    if WRITE_GLOBAL_TRANSCRIPT:
        open(GLOBAL_TRANSCRIPT_FILE, "a", encoding="utf-8").close()

    print(f"Connecting to Realtime API with model: {MODEL}", flush=True)
    async with websockets.connect(url, additional_headers=headers, max_size=2**24) as ws:
        print("Connected to Realtime API.", flush=True)
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "input_audio_format": "pcm16",
                        "input_audio_noise_reduction": {"type": "near_field"},
                        "input_audio_transcription": {
                            "model": TRANSCRIBE_MODEL,
                            "prompt": TRANSCRIBE_PROMPT,
                            "language": TRANSCRIBE_LANG,
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": VAD_THRESHOLD,
                            "prefix_padding_ms": VAD_PREFIX_MS,
                            "silence_duration_ms": VAD_SILENCE_MS,
                            "create_response": False,
                        },
                    },
                }
            )
        )
        print(f"Transcription model set to: {TRANSCRIBE_MODEL}", flush=True)
        print(
            "VAD settings: "
            f"threshold={VAD_THRESHOLD}, "
            f"prefix_padding_ms={VAD_PREFIX_MS}, "
            f"silence_ms={VAD_SILENCE_MS}",
            flush=True,
        )
        print(f"Session transcript: {session_transcript_file}", flush=True)
        if WRITE_GLOBAL_TRANSCRIPT:
            print(f"Global transcript: {GLOBAL_TRANSCRIPT_FILE}", flush=True)
        print("Listening... start speaking.", flush=True)

        sender = asyncio.create_task(send_audio(ws, stats))
        receiver = asyncio.create_task(
            receive_events(ws, stats, session_transcript_file, GLOBAL_TRANSCRIPT_FILE)
        )
        metrics = asyncio.create_task(metrics_reporter(stats))

        done, pending = await asyncio.wait(
            [sender, receiver, metrics], return_when=asyncio.FIRST_EXCEPTION
        )
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                raise exc


if __name__ == "__main__":
    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    print("Realtime prototype started. Press Ctrl+C to stop.")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"\nStartup/runtime error: {exc}")
        print("Tip: verify OPENAI_API_KEY and model access.")
