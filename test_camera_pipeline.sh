echo "Stopping any existing ffmpeg/mediamtx..."
pkill -f ffmpeg
pkill -f mediamtx
sleep 1
echo "Starting stream..."
./tools/start_stream.sh &
STREAM_PID=$!
sleep 3
echo "Running python test..."
venv/bin/python live_stream_model.py &
PYTHON_PID=$!
sleep 5
echo "Stopping all..."
kill $STREAM_PID
kill $PYTHON_PID
