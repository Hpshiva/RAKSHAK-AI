#!/usr/bin/env bash
set -e

export OPENCV_LOG_LEVEL=FATAL

if [ -x "venv/bin/python" ]; then
  exec venv/bin/python app.py
fi

exec python app.py
