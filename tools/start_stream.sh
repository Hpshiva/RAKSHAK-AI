#!/bin/bash

# ==============================================================================
# FFmpeg Zero-Latency Stream Capture Script (macOS)
# ==============================================================================
# This script captures the video feed from a Virtual Camera (or physical camera)
# and pushes it to your local MediaMTX server with zero latency.
# ==============================================================================

# STEP 1: Find your camera device index
# Run this command in your terminal to see a list of connected cameras:
# ./ffmpeg -f avfoundation -list_devices true -i ""
# Look for "OBS Virtual Camera" or your specific camera name and note its index number (e.g., "0", "1", "2").

DEVICE_INDEX="0" # Change this to the index of your camera!

echo "Starting FFmpeg stream from device index $DEVICE_INDEX..."
# STEP 2: Start the stream
# Breakdown of parameters:
# -f avfoundation : The macOS camera framework.
# -framerate 30   : Capture at 30 frames per second.
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

if [ ! -f "$DIR/ffmpeg" ]; then
    echo "Error: ffmpeg binary not found in $DIR"
    exit 1
fi

echo "Starting FFmpeg direct UDP stream from device index $DEVICE_INDEX..."
echo "This bypasses MediaMTX directly to the AI model."
echo "Press Ctrl+C to stop."

while true; do
    "$DIR/ffmpeg" -v error -f avfoundation -pixel_format uyvy422 -framerate 30 -video_size 1280x720 -i "$DEVICE_INDEX" \
        -fps_mode vfr \
        -vf "hflip" \
        -c:v rawvideo -pix_fmt bgr24 \
        -an \
        -f nut \
        "tcp://127.0.0.1:12345?listen=1"
        
    echo "Python AI model disconnected. Waiting for a new connection..."
    sleep 1
done
