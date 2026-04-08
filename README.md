# Whspr

Simple local realtime transcription toolkit for macOS.

## Features

- Realtime microphone transcription via OpenAI Realtime API
- Chunked microphone transcription via OpenAI Transcriptions API
- Low-latency streaming output in terminal
- Automatic transcript persistence to `~/AudioLogs`
- Simple UI with `Realtime` and `Chunked` modes

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

## Primary Script

- `realtime_prototype.py` - Realtime transcription runner (project default)
- `chunked_transcribe.py` - Chunk-based transcription runner (separate mode)

## Quick Start

### Realtime Transcription

```bash
bash "$HOME/AudioRecorder/start_realtime_prototype.command"
```

### Simple UI

```bash
bash "$HOME/AudioRecorder/start_simple_ui.command"
```

UI controls:

- `Record/Stop` is a single toggle button
- `Mode` dropdown lets you switch between `Realtime` and `Chunked`
- Transcript panel auto-refreshes from the selected mode's latest session file

Set default UI mode in `.env`:

```env
UI_TRANSCRIBE_MODE=realtime
# or
UI_TRANSCRIBE_MODE=chunked
```

### Chunked Transcription (Separate)

```bash
bash "$HOME/AudioRecorder/start_chunked_transcribe.command"
```

Defaults:

- Model: `gpt-4o-mini-transcribe`
- Chunk size: `4` seconds
- Transcript output: `~/AudioLogs/chunked_session_YYYYMMDD_HHMMSS.txt`

Output transcript file:

- `~/AudioLogs/realtime_transcript.txt`
- Per-session file: `~/AudioLogs/realtime_session_YYYYMMDD_HHMMSS.txt`

## Tuning

You can override defaults per run with environment variables:

```bash
OPENAI_REALTIME_MODEL=gpt-4o-realtime-preview OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe bash "$HOME/AudioRecorder/start_realtime_prototype.command"
```

Optional environment variables used by `realtime_prototype.py`:

- `OPENAI_REALTIME_MODEL` (default: `gpt-4o-realtime-preview`)
- `OPENAI_TRANSCRIBE_MODEL` (default: `gpt-4o-mini-transcribe`)
- `OPENAI_TRANSCRIBE_LANGUAGE` (default: `en`)
- `OPENAI_TRANSCRIBE_PROMPT` (default: empty)
- `OPENAI_REALTIME_DEBUG=1` to print event diagnostics
- `SAVE_AUDIO=1` to save one `.wav` recording per session (default: off)
- `SAVE_AUDIO_DIR` to override audio output directory (default: `~/AudioLogs`)
- `STABILIZE_PARTIALS=1` to reduce partial-word flicker in live output (default: on)
- `POST_PROCESS_FINAL=1` to lightly clean final transcript turns (default: on)
- `VAD_THRESHOLD` voice activity threshold (default: `0.5`)
- `VAD_PREFIX_PADDING_MS` speech prefix padding in ms (default: `300`)
- `VAD_SILENCE_MS` silence window to finalize a turn in ms (default: `500`)
- `METRICS_INTERVAL_SEC` periodic runtime metrics interval (default: `5`)
- `TRANSCRIPT_DIR` transcript output directory (default: `~/AudioLogs`)
- `GLOBAL_TRANSCRIPT_FILENAME` global rolling transcript filename (default: `realtime_transcript.txt`)
- `WRITE_GLOBAL_TRANSCRIPT=0` to disable writing to global rolling transcript

Optional environment variables used by `chunked_transcribe.py`:

- `OPENAI_TRANSCRIBE_MODEL` (default: `gpt-4o-mini-transcribe`)
- `CHUNK_SECONDS` (default: `4`)
- `CHUNK_SAMPLE_RATE` (default: `16000`)
- `SAVE_CHUNKS=1` to keep chunk `.wav` files (default: off)
- `TRANSCRIPT_DIR` output directory (default: `~/AudioLogs`)

Example with audio saving:

```bash
SAVE_AUDIO=1 bash "$HOME/AudioRecorder/start_realtime_prototype.command"
```

Example tuned for cleaner segmentation:

```bash
VAD_THRESHOLD=0.45 VAD_SILENCE_MS=650 STABILIZE_PARTIALS=1 METRICS_INTERVAL_SEC=3 bash "$HOME/AudioRecorder/start_realtime_prototype.command"
```

Chunked quick example:

```bash
OPENAI_TRANSCRIBE_MODEL=gpt-4o-mini-transcribe CHUNK_SECONDS=3 bash "$HOME/AudioRecorder/start_chunked_transcribe.command"
```

## Notes

- First run may trigger macOS microphone permission prompt.
- If a process hangs, stop with `Ctrl+C` or:

```bash
pkill -f realtime_prototype.py
```

- Revoke any API keys that were accidentally exposed and generate fresh keys.
