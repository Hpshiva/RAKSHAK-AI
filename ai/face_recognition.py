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
        self.lbph = None
        self.lbph_names = {}
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bundled_cascade = os.path.join(
            project_root,
            "FaceRecognition-GUI-APP-master",
            "data",
            "haarcascade_frontalface_default.xml",
        )
        default_cascade = os.path.join(
            getattr(cv2.data, "haarcascades", ""),
            "haarcascade_frontalface_default.xml",
        )
        cascade_path = bundled_cascade if os.path.exists(bundled_cascade) else default_cascade
        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        if INSIGHTFACE_AVAILABLE:
            # Use antelopev2 or buffalo_l for recognition. buffalo_l is default robust.
            try:
                self.app = FaceAnalysis(name='buffalo_l', allowed_modules=['recognition', 'detection'])
                self.app.prepare(ctx_id=0, det_size=(640, 640))
                print(" Face Recognition Model Loaded Successfully")
            except Exception as e:
                print("Failed to load FaceAnalysis:", e)
                self.app = None

        if self.app is None and hasattr(cv2, "face"):
            self.lbph = cv2.face.LBPHFaceRecognizer_create()
            print(" Face Recognition: using OpenCV LBPH fallback")

    @staticmethod
    def _display_name(filename):
        if '__' in filename:
            parts = filename.split('__')
            return f"{parts[0].replace('_', ' ')} ({parts[1].replace('_', ' ')})"
        parts = filename.split('_')
        return (parts[0] if len(parts) > 1 else filename.rsplit('.', 1)[0]).replace('_', ' ')
                
    def load_faces(self, faces_dir):
        self.known_faces = []
        self.lbph_names = {}
        if not os.path.exists(faces_dir):
            return

        lbph_images = []
        lbph_labels = []
        print(f"Loading known faces from {faces_dir}...")
        for filename in os.listdir(faces_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                filepath = os.path.join(faces_dir, filename)
                img = cv2.imread(filepath)
                if img is not None:
                    name = self._display_name(filename)
                    if self.app:
                        faces = self.app.get(img)
                    else:
                        faces = []

                    if self.app and faces:
                        # Grab the most prominent face
                        embedding = faces[0].embedding
                        self.known_faces.append((name, embedding))
                    elif self.lbph is not None:
                        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                        detected = self.face_cascade.detectMultiScale(
                            gray, scaleFactor=1.1, minNeighbors=4, minSize=(50, 50)
                        )
                        if len(detected):
                            x, y, w, h = max(detected, key=lambda box: box[2] * box[3])
                            label = len(self.lbph_names)
                            self.lbph_names[label] = name
                            lbph_images.append(cv2.resize(gray[y:y + h, x:x + w], (160, 160)))
                            lbph_labels.append(label)

        if self.lbph is not None and lbph_images:
            self.lbph.train(lbph_images, np.asarray(lbph_labels, dtype=np.int32))
            print(f"Loaded {len(lbph_images)} known faces with OpenCV LBPH.")
        else:
            print(f"Loaded {len(self.known_faces)} known faces.")

    def recognize_faces(self, frame):
        """
        Returns a list of dicts with recognized names and their face bounding boxes.
        """
        if not self.app:
            if self.lbph is None or not self.lbph_names:
                return []

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            detected = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(55, 55)
            )
            recognized_faces = []
            for x, y, w, h in detected:
                face_crop = cv2.resize(gray[y:y + h, x:x + w], (160, 160))
                label, distance = self.lbph.predict(face_crop)
                name = self.lbph_names.get(label, "Unknown") if distance < 85 else "Unknown"
                recognized_faces.append({"name": name, "bbox": [x, y, x + w, y + h]})
            return recognized_faces

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
