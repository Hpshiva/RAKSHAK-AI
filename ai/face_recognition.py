import os
import cv2
import numpy as np

# We lazy load insightface so it doesn't crash if not installed
try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False

class FaceRecognizer:
    def __init__(self):
        self.app = None
        self.known_faces = []
        if INSIGHTFACE_AVAILABLE:
            # Use antelopev2 or buffalo_l for recognition. buffalo_l is default robust.
            try:
                self.app = FaceAnalysis(name='buffalo_l', allowed_modules=['recognition', 'detection'])
                self.app.prepare(ctx_id=0, det_size=(640, 640))
                print(" Face Recognition Model Loaded Successfully")
            except Exception as e:
                print("Failed to load FaceAnalysis:", e)
                self.app = None
                
    def load_faces(self, faces_dir):
        self.known_faces = []
        if not self.app or not os.path.exists(faces_dir):
            return
            
        print(f"Loading known faces from {faces_dir}...")
        for filename in os.listdir(faces_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                filepath = os.path.join(faces_dir, filename)
                img = cv2.imread(filepath)
                if img is not None:
                    faces = self.app.get(img)
                    if faces:
                        # Grab the most prominent face
                        embedding = faces[0].embedding
                        parts = filename.split('_')
                        name = parts[0] if len(parts) > 1 else filename.split('.')[0]
                        self.known_faces.append((name, embedding))
        print(f"Loaded {len(self.known_faces)} known faces.")

    def recognize_faces(self, frame):
        """
        Returns a list of dicts with recognized names and their face bounding boxes.
        """
        if not self.app:
            return []
            
        faces = self.app.get(frame)
        if not faces:
            return []
            
        recognized_faces = []
        for face in faces:
            emb = face.embedding
            bbox = face.bbox.astype(int).tolist() # [x1, y1, x2, y2]
            best_match = "Unknown"
            min_dist = 1.0 # cosine distance threshold
            
            for name, known_emb in self.known_faces:
                # Cosine distance
                dist = 1 - np.dot(emb, known_emb) / (np.linalg.norm(emb) * np.linalg.norm(known_emb))
                # 0.6 is a standard threshold for ArcFace
                if dist < min_dist and dist < 0.6:
                    min_dist = dist
                    best_match = name
                    
            recognized_faces.append({"name": best_match, "bbox": bbox})
            
        return recognized_faces
