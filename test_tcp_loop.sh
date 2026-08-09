#!/bin/bash
./tools/ffmpeg -v error -f lavfi -i "testsrc=size=1280x720:rate=30" \
    -vf "hflip,scale=1280:720,format=yuv420p" \
    -c:v libx264 -preset ultrafast -tune zerolatency -b:v 2M \
    -f mpegts "tcp://127.0.0.1:12346?listen=1"
