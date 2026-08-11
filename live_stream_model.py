import cv2
import threading
import time

class ZeroLatencyStream:
    """
    This class continuously grabs frames from the RTSP stream in a background thread.
    This guarantees that the AI model always gets the absolute latest frame, 
    eliminating the 1-second lag caused by OpenCV's internal frame buffer.
    """
    def __init__(self, stream_url="tcp://127.0.0.1:12345", max_fps=30):
        self.stream_url = stream_url
        self.max_fps = max_fps
        self.latest_frame = None
        self.running = True
        
        # Open the stream using FFmpeg backend explicitly for better UDP/TCP support
        self.capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
        
        if not self.capture.isOpened():
            print(f"Warning: Could not open video stream at {self.stream_url} yet. Will retry...")
            
        # Start a background thread to continuously read frames
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            if not self.capture.isOpened():
                print("Stream lost, attempting to reconnect...")
                time.sleep(1)
                self.capture = cv2.VideoCapture(self.stream_url, cv2.CAP_FFMPEG)
                continue
                
            ret, frame = self.capture.read()
            if ret:
                self.latest_frame = frame
            else:
                self.capture.release()

    def get_latest_frame(self):
        """Returns the most recent frame grabbed from the stream."""
        return self.latest_frame

    def stop(self):
        self.running = False
        self.thread.join()
        self.capture.release()

# --- AI Model Integration Example ---

def run_ai_pipeline():
    # Connect to the local FFmpeg TCP server
    TCP_URL = "tcp://127.0.0.1:12345"
    print(f"Connecting to AI live feed: {TCP_URL}")
    
    stream = ZeroLatencyStream(TCP_URL)
    
    # Wait a moment for the first frame to buffer
    time.sleep(1)
    
    if stream.get_latest_frame() is None:
        print("Failed to get initial frame. Make sure MediaMTX and FFmpeg are running.")
        stream.stop()
        return

    print("Successfully connected! Running AI Model...")
    
    # Create a resizable window that scales properly when made fullscreen
    cv2.namedWindow("AI Model View - Live Feed", cv2.WINDOW_NORMAL)
    
    try:
        while True:
            # 2. Get the absolute latest frame (Zero Latency)
            frame = stream.get_latest_frame()
            
            if frame is not None:
                # ----------------------------------------------------
                # [YOUR AI MODEL CODE GOES HERE]
                # Example: results = model.predict(frame)
                # ----------------------------------------------------
                
                # For demonstration, we just show the live feed
                cv2.imshow("AI Model View - Live Feed", frame)
            
            # Press 'q' to quit
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
                
    except KeyboardInterrupt:
        print("\nPipeline stopped by user.")
    finally:
        print("Cleaning up...")
        stream.stop()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    # Note: To run this, you need OpenCV installed: 
    # pip install opencv-python
    run_ai_pipeline()
