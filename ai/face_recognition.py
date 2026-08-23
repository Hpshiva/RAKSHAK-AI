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
        cascade_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "models",
            "haarcascade_frontalface_default.xml",
        )
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

        # Python 3.14 currently has no reliable InsightFace/ONNX wheel. Use
        # OpenCV's local LBPH recognizer so registered names still work.
        if self.app is None and hasattr(cv2, "face"):
            self.lbph = cv2.face.LBPHFaceRecognizer_create(1, 8, 8, 8, 85.0)
            print(" OpenCV Face Recognition Fallback Ready")

    @staticmethod
    def _display_name(filename):
        if '__' in filename:
            parts = filename.split('__')
            return f"{parts[0].replace('_', ' ')} ({parts[1]})"
        parts = filename.rsplit('.', 1)[0].split('_')
        return parts[0].replace('_', ' ') if len(parts) > 1 else parts[0]

    @staticmethod
    def _prepare_face(gray_face):
        resized = cv2.resize(gray_face, (160, 160), interpolation=cv2.INTER_AREA)
        return cv2.equalizeHist(resized)
                
    def load_faces(self, faces_dir):
        self.known_faces = []
        self.lbph_names = {}
        if not os.path.exists(faces_dir):
            return
            
        print(f"Loading known faces from {faces_dir}...")
        for filename in os.listdir(faces_dir):
            if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                filepath = os.path.join(faces_dir, filename)
                img = cv2.imread(filepath)
                if img is not None:
                    if self.app:
                        faces = self.app.get(img)
                    else:
                        faces = []
                    if self.app and faces:
                        # Grab the most prominent face
                        embedding = faces[0].embedding
                        name = self._display_name(filename)
                        self.known_faces.append((name, embedding))
        if self.app:
            print(f"Loaded {len(self.known_faces)} known faces.")
            return

        training_faces = []
        training_labels = []
        for filename in os.listdir(faces_dir):
            if not filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            img = cv2.imread(os.path.join(faces_dir, filename))
            if img is None:
                continue
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            boxes = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
            )
            if len(boxes) == 0:
                continue
            x, y, w, h = max(boxes, key=lambda box: box[2] * box[3])
            prepared = self._prepare_face(gray[y:y + h, x:x + w])
            label = len(self.lbph_names)
            self.lbph_names[label] = self._display_name(filename)
            # Lightweight augmentation improves matching under webcam lighting.
            variants = [prepared, cv2.flip(prepared, 1)]
            for variant in variants:
                training_faces.append(variant)
                training_labels.append(label)
        if self.lbph is not None and training_faces:
            self.lbph.train(training_faces, np.asarray(training_labels))
        print(f"Loaded {len(self.lbph_names)} known faces with OpenCV fallback.")

    def recognize_faces(self, frame):
        """
        Returns a list of dicts with recognized names and their face bounding boxes.
        """
        if not self.app:
            if self.lbph is None or not self.lbph_names:
                return []
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            boxes = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.08, minNeighbors=5, minSize=(55, 55)
            )
            recognized_faces = []
            for x, y, w, h in boxes:
                prepared = self._prepare_face(gray[y:y + h, x:x + w])
                label, confidence = self.lbph.predict(prepared)
                name = self.lbph_names.get(label, "Unknown") if confidence <= 85 else "Unknown"
                recognized_faces.append({
                    "name": name,
                    "bbox": [int(x), int(y), int(x + w), int(y + h)],
                    "confidence": round(max(0.0, 100.0 - confidence), 1),
                })
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
