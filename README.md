# Whspr

Simple local audio recording and transcription toolkit for macOS.

## Features

- Manual audio recording (single file per run)
- Chunked transcription (near real-time, currently 4-second chunks)
- Live desktop UI for transcript viewing (Start/Stop + auto-refresh)
- Optional Realtime API prototype script (kept for reference)

## Requirements

- macOS
- Python 3.13+ (project currently uses pyenv Python at `/Users/sbstfrnndz/.pyenv/versions/3.13.7/bin/python`)
- OpenAI API key exported in your shell:

```bash
export OPENAI_API_KEY="YOUR_KEY"
```

## Install Dependencies

```bash
/Users/sbstfrnndz/.pyenv/versions/3.13.7/bin/python -m pip install openai sounddevice soundfile numpy websockets python-dotenv
```

## Project Scripts

- `recorder.py` - Manual audio recorder (single `.wav` per run)
- `chunked_transcribe.py` - Chunked recorder + transcription (default model + chunk config)
- `live_transcript_ui.py` - Tkinter UI that starts/stops chunked transcription and shows live transcript
- `transcribe_recording.py` - Transcribe latest or specified `.wav` file
- `realtime_prototype.py` - Realtime transcription experiment (optional)

## Quick Start

### 1) Manual Recorder Only

```bash
bash "$HOME/AudioRecorder/start_recorder.command"
```

Output audio files: `~/AudioLogs`

### 2) Chunked Transcription (Terminal Live Output)

```bash
bash "$HOME/AudioRecorder/start_chunked_transcribe.command"
```

Current defaults in `chunked_transcribe.py`:

- Model: `gpt-4o-mini-transcribe`
- Chunk size: `4` seconds

Output:

- Chunk `.wav` files in `~/AudioLogs`
- Session transcript file like `~/AudioLogs/session_YYYYMMDD_HHMMSS.txt`

### 3) Live UI

```bash
bash "$HOME/AudioRecorder/start_live_transcript_ui.command"
```

In UI:

- Click **Start** to begin chunked transcription
- Click **Stop** to stop
- Transcript panel auto-refreshes from latest session file

## Model / Speed Tuning

You can override defaults per run with environment variables:

```bash
OPENAI_TRANSCRIBE_MODEL=gpt-4o-transcribe CHUNK_SECONDS=6 bash "$HOME/AudioRecorder/start_chunked_transcribe.command"
```

Recommended presets:

- Fast + cheap: `gpt-4o-mini-transcribe` with 4s chunks
- Better accuracy: `gpt-4o-transcribe` with 6-8s chunks

## Notes

- First run may trigger macOS microphone permission prompt.
- If a process hangs, stop with `Ctrl+C` or:

```bash
pkill -f chunked_transcribe.py
pkill -f recorder.py
```

- Revoke any API keys that were accidentally exposed and generate fresh keys.
