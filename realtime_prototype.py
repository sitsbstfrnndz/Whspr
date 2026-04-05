import asyncio
import base64
import json
import os
import signal
from datetime import datetime

import numpy as np
import sounddevice as sd
import websockets

API_KEY = os.getenv("OPENAI_API_KEY", "")
MODEL = os.getenv("OPENAI_REALTIME_MODEL", "gpt-4o-realtime-preview")
TRANSCRIBE_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
DEBUG_EVENTS = os.getenv("OPENAI_REALTIME_DEBUG", "0") == "1"

SAMPLE_RATE = 16000
CHANNELS = 1
FRAMES_PER_CHUNK = 3200  # 200ms
TRANSCRIPT_FILE = os.path.expanduser("~/AudioLogs/realtime_transcript.txt")

running = True


def stop_handler(signum, frame):
    global running
    running = False


def float_to_pcm16_bytes(audio: np.ndarray) -> bytes:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767).astype(np.int16)
    return pcm16.tobytes()


async def send_audio(ws):
    sent_chunks = 0
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        print("Microphone stream opened.", flush=True)
        while running:
            # stream.read is blocking; run it in a thread to keep asyncio responsive.
            frames, _ = await asyncio.to_thread(stream.read, FRAMES_PER_CHUNK)
            mono = frames[:, 0] if frames.ndim > 1 else frames
            payload = base64.b64encode(float_to_pcm16_bytes(mono)).decode("ascii")

            await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": payload}))
            sent_chunks += 1

            if DEBUG_EVENTS and sent_chunks % 20 == 0:
                print(f"[debug] sent_chunks={sent_chunks}", flush=True)

            await asyncio.sleep(0)


async def receive_events(ws):
    os.makedirs(os.path.dirname(TRANSCRIPT_FILE), exist_ok=True)
    full_text_parts = []

    while running:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            continue

        event = json.loads(raw)
        event_type = event.get("type", "")

        if DEBUG_EVENTS:
            print(f"\n[event] {event_type}", flush=True)

        if event_type in ("response.output_text.delta", "response.text.delta"):
            delta = event.get("delta", "")
            if delta:
                print(delta, end="", flush=True)
                full_text_parts.append(delta)

        elif event_type == "conversation.item.input_audio_transcription.delta":
            delta = event.get("delta", "")
            if delta:
                print(delta, end="", flush=True)
                full_text_parts.append(delta)

        elif event_type == "conversation.item.input_audio_transcription.completed":
            transcript = event.get("transcript", "")
            if transcript:
                print(transcript, flush=True)
                full_text_parts.append(transcript + "\n")

        elif event_type == "error":
            print("\nRealtime API error:", event.get("error", event), flush=True)

    text = "".join(full_text_parts).strip()
    if text:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(TRANSCRIPT_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[{stamp}]\n{text}\n")
        print(f"\nSaved transcript to: {TRANSCRIPT_FILE}")


async def main():
    if not API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not set.")

    url = f"wss://api.openai.com/v1/realtime?model={MODEL}"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "OpenAI-Beta": "realtime=v1",
    }

    print(f"Connecting to Realtime API with model: {MODEL}", flush=True)
    async with websockets.connect(url, additional_headers=headers, max_size=2**24) as ws:
        print("Connected to Realtime API.", flush=True)
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "input_audio_format": "pcm16",
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 700,
                            "create_response": False,
                        },
                        "input_audio_transcription": {"model": TRANSCRIBE_MODEL},
                    },
                }
            )
        )
        print(f"Transcription model set to: {TRANSCRIBE_MODEL}", flush=True)
        print("Listening... start speaking.", flush=True)

        sender = asyncio.create_task(send_audio(ws))
        receiver = asyncio.create_task(receive_events(ws))

        done, pending = await asyncio.wait(
            [sender, receiver], return_when=asyncio.FIRST_EXCEPTION
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
