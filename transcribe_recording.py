import argparse
import os
from pathlib import Path

from openai import OpenAI

DEFAULT_MODEL = os.getenv("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
AUDIO_DIR = Path(os.path.expanduser("~/AudioLogs"))


def get_latest_wav(audio_dir: Path) -> Path:
    wav_files = sorted(audio_dir.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not wav_files:
        raise FileNotFoundError(f"No .wav files found in {audio_dir}")
    return wav_files[0]


def transcribe_file(audio_path: Path, model: str) -> str:
    client = OpenAI()
    with audio_path.open("rb") as f:
        text = client.audio.transcriptions.create(model=model, file=f, response_format="text")
    # SDK returns plain text string for response_format='text'.
    return str(text).strip()


def save_transcript(audio_path: Path, text: str) -> Path:
    out_path = audio_path.with_suffix(".txt")
    out_path.write_text(text + "\n", encoding="utf-8")
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Transcribe a recording with OpenAI transcription model.")
    parser.add_argument("file", nargs="?", help="Path to .wav file. If omitted, uses latest file in ~/AudioLogs")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Transcription model name")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set.")

    audio_path = Path(args.file).expanduser() if args.file else get_latest_wav(AUDIO_DIR)
    if not audio_path.exists():
        raise FileNotFoundError(f"File not found: {audio_path}")

    print(f"Transcribing: {audio_path}")
    print(f"Model: {args.model}")
    text = transcribe_file(audio_path, args.model)
    out_path = save_transcript(audio_path, text)
    print(f"Saved transcript: {out_path}")


if __name__ == "__main__":
    main()
