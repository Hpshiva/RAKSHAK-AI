#!/bin/bash

echo "==========================================="
echo " Starting Rakshak AI Live Pipeline"
echo "==========================================="

# Start the FFmpeg streaming script in the background
echo "1. Initializing Camera Stream..."
./tools/start_stream.sh &
STREAM_PID=$!

# Give it a second to boot up
sleep 4

# Activate virtual environment and run the python app
echo "2. Starting AI Model..."
source venv/bin/activate
export OPENCV_LOG_LEVEL=FATAL
python live_stream_model.py

# When the python script exits (user presses 'q' or closes it)
echo "Cleaning up background processes..."
kill $STREAM_PID
# Make sure any lingering ffmpeg processes are also killed
pkill -f "ffmpeg -f avfoundation"

echo "Done!"
