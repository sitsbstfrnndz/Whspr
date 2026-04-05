#!/bin/zsh
cd "$HOME/AudioRecorder" || exit 1
/Users/sbstfrnndz/.pyenv/versions/3.13.7/bin/python recorder.py
echo ""
echo "Recorder stopped. Press Enter to close."
read
