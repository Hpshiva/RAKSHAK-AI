import urllib.request
import threading
import time
import subprocess
import os

print("Starting server...")
process = subprocess.Popen(["venv/bin/python", "app.py"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def read_output():
    for line in process.stdout:
        print(f"[SERVER] {line.strip()}")

threading.Thread(target=read_output, daemon=True).start()

time.sleep(15) # Wait for models to load

print("Making request to /camera_feed/0...")
try:
    req = urllib.request.Request("http://127.0.0.1:5001/camera_feed/0")
    # Need to simulate being logged in to access camera_feed
    # Let's bypass login check for testing!
except Exception as e:
    print(e)
    
process.terminate()
