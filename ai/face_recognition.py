import os
import cv2
import numpy as np

# Lazy load InsightFace if available
try:
    from insightface.app import FaceAnalysis
    INSIGHTFACE_AVAILABLE = True
except ImportError:
    INSIGHTFACE_AVAILABLE = False


class FaceRecognizer:
    """
    Advanced Face Recognition Module.
    Primary Engine: OpenCV Deep Learning (YuNet for 5-landmark face detection + SFace for 128-d deep embeddings).
    Secondary Engine: InsightFace (ArcFace / MobileFaceNet).
    Fallback Engine: OpenCV Haar Cascade + LBPH (classical fallback).
    """

    def __init__(self):
        self.engine = "none"
        self.known_faces = [] # list of (name, [embeddings])
        self.yunet = None
        self.sface = None
        self.app = None
        self.lbph = None
        self.lbph_names = {}

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir = os.path.join(base_dir, "models")
        yunet_path = os.path.join(models_dir, "face_detection_yunet_2023mar.onnx")
        sface_path = os.path.join(models_dir, "face_recognition_sface_2021dec.onnx")
        cascade_path = os.path.join(models_dir, "haarcascade_frontalface_default.xml")
        self.face_cascade = cv2.CascadeClassifier(cascade_path)

        # 1. Try OpenCV Deep Learning (YuNet + SFace) - Fast, Deep, Highly Accurate
        if (
            os.path.isfile(yunet_path)
            and os.path.isfile(sface_path)
            and hasattr(cv2, "FaceDetectorYN_create")
            and hasattr(cv2, "FaceRecognizerSF_create")
        ):
            try:
                self.yunet = cv2.FaceDetectorYN_create(
                    model=yunet_path,
                    config="",
                    input_size=(320, 320),
                    score_threshold=0.60,
                    nms_threshold=0.30,
                    top_k=5000,
                )
                self.sface = cv2.FaceRecognizerSF_create(
                    model=sface_path,
                    config="",
                )
                self.engine = "sface"
                print(" Face Recognition Engine: OpenCV Deep Learning (YuNet + SFace 128-D)")
            except Exception as e:
                print("Failed to initialize YuNet/SFace:", e)
                self.yunet = None
                self.sface = None

        # 2. Try InsightFace if available and SFace is not used
        if self.engine == "none" and INSIGHTFACE_AVAILABLE:
            try:
                self.app = FaceAnalysis(name="buffalo_l", allowed_modules=["recognition", "detection"])
                self.app.prepare(ctx_id=0, det_size=(640, 640))
                self.engine = "insightface"
                print(" Face Recognition Engine: InsightFace (ArcFace)")
            except Exception as e:
                print("Failed to load FaceAnalysis:", e)
                self.app = None

        # 3. Classical Fallback (LBPH)
        if self.engine == "none" and hasattr(cv2, "face"):
            self.lbph = cv2.face.LBPHFaceRecognizer_create(1, 8, 8, 8, 85.0)
            self.engine = "lbph"
            print(" Face Recognition Engine: OpenCV Classical Fallback (LBPH)")

    @staticmethod
    def _display_name(filename):
        if "__" in filename:
            parts = filename.split("__")
            return f"{parts[0].replace('_', ' ')} ({parts[1]})"
        parts = filename.rsplit(".", 1)[0].split("_")
        return parts[0].replace("_", " ") if len(parts) > 1 else parts[0]

    @staticmethod
    def _prepare_face(gray_face):
        resized = cv2.resize(gray_face, (160, 160), interpolation=cv2.INTER_AREA)
        return cv2.equalizeHist(resized)

    @staticmethod
    def check_liveness(face_crop):
        """
        Anti-Spoofing & Liveness Detection (Phase 1 hardening).
        Rejects 2D printouts, photocopies, and digital screens via:
        - Texture sharpness (Laplacian variance)
        - Chromatic diversity (HSV distribution)
        - High-frequency screen moiré analysis (2D FFT energy ratio)
        """
        if face_crop is None or face_crop.size < 400:
            return {"is_live": True, "liveness_score": 50.0, "reason": "Insufficient resolution"}

        try:
            resized = cv2.resize(face_crop, (160, 160))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)

            # 1. Texture richness & sharpness
            lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())

            # 2. Chromatic diversity (HSV check for grayscale photocopy or washed-out screen)
            hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
            sat = hsv[:, :, 1]
            sat_mean = float(np.mean(sat))
            sat_std = float(np.std(sat))

            # 3. Frequency domain (Screen moiré check via 2D FFT)
            f = np.fft.fft2(gray)
            fshift = np.fft.fftshift(f)
            mag = np.abs(fshift) + 1e-7
            cy, cx = 80, 80
            y, x = np.ogrid[:160, :160]
            low_mask = (x - cx) ** 2 + (y - cy) ** 2 <= 20 ** 2
            low_energy = np.sum(mag[low_mask])
            high_energy = np.sum(mag[~low_mask])
            fft_ratio = float(high_energy / (low_energy + 1e-5))

            is_spoof = False
            reason = "Genuine live presentation"

            if sat_mean < 4.0 and sat_std < 3.0:
                is_spoof = True
                reason = "Photocopy / Grayscale Spoof"
            elif lap_var < 3.0:
                is_spoof = True
                reason = "Low-Resolution / Defocus Spoof"
            elif fft_ratio > 3.8:
                is_spoof = True
                reason = "Screen Moiré Pattern"

            score = 25.0 if is_spoof else min(99.0, max(65.0, 70.0 + min(20.0, lap_var / 5.0) - abs(fft_ratio - 0.75) * 15.0))

            return {
                "is_live": not is_spoof,
                "liveness_score": round(score, 1),
                "reason": reason,
                "metrics": {
                    "lap_var": round(lap_var, 1),
                    "sat_mean": round(sat_mean, 1),
                    "fft_ratio": round(fft_ratio, 3),
                }
            }
        except Exception:
            return {"is_live": True, "liveness_score": 80.0, "reason": "Liveness analysis fallback"}

    def load_faces(self, faces_dir):
        """
        Enrolls faces from directory with multi-sample grouping and deep feature extraction.
        """
        self.known_faces = []
        self.lbph_names = {}
        if not os.path.exists(faces_dir):
            return

        print(f"Loading known faces from {faces_dir}...")
        face_groups = {} # name -> list of embeddings

        for filename in sorted(os.listdir(faces_dir)):
            if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                continue
            filepath = os.path.join(faces_dir, filename)
            img = cv2.imread(filepath)
            if img is None:
                continue

            name = self._display_name(filename)

            # SFace enrollment
            if self.engine == "sface":
                h, w = img.shape[:2]
                self.yunet.setInputSize((w, h))
                _, detected_faces = self.yunet.detect(img)
                if detected_faces is not None and len(detected_faces) > 0:
                    # Select largest face in reference image
                    primary_face = max(detected_faces, key=lambda f: f[2] * f[3])
                    aligned_face = self.sface.alignCrop(img, primary_face)
                    feature = self.sface.feature(aligned_face)
                    # Normalize feature
                    feature = feature / np.linalg.norm(feature)
                    face_groups.setdefault(name, []).append(feature)

            # InsightFace enrollment
            elif self.engine == "insightface":
                faces = self.app.get(img)
                if faces:
                    primary_face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                    emb = primary_face.embedding / np.linalg.norm(primary_face.embedding)
                    face_groups.setdefault(name, []).append(emb)

        if self.engine in ("sface", "insightface") and face_groups:
            for name, embeddings in face_groups.items():
                self.known_faces.append((name, embeddings))
            print(f"Loaded {len(self.known_faces)} distinct enrolled identities ({sum(len(e) for e in face_groups.values())} reference photos).")
            return

        # LBPH enrollment fallback
        training_faces = []
        training_labels = []
        for filename in sorted(os.listdir(faces_dir)):
            if not filename.lower().endswith((".png", ".jpg", ".jpeg")):
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
            prepared = self._prepare_face(gray[y : y + h, x : x + w])
            label = len(self.lbph_names)
            self.lbph_names[label] = self._display_name(filename)
            variants = [prepared, cv2.flip(prepared, 1)]
            for variant in variants:
                training_faces.append(variant)
                training_labels.append(label)

        if self.lbph is not None and training_faces:
            self.lbph.train(training_faces, np.asarray(training_labels))
            print(f"Loaded {len(self.lbph_names)} known faces with OpenCV LBPH fallback.")

    def recognize_faces(self, frame):
        """
        Detects, aligns, and recognizes faces in frame.
        Returns list of dicts: [{"name": str, "bbox": [x1, y1, x2, y2], "confidence": float, "is_live": bool}]
        """
        if frame is None or frame.size == 0:
            return []

        # 1. OpenCV Deep Learning (YuNet + SFace)
        if self.engine == "sface":
            h, w = frame.shape[:2]
            self.yunet.setInputSize((w, h))
            _, detected_faces = self.yunet.detect(frame)
            if detected_faces is None or len(detected_faces) == 0:
                return []

            recognized = []
            for face in detected_faces:
                x, y, box_w, box_h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
                bbox = [max(0, x), max(0, y), min(w, x + box_w), min(h, y + box_h)]
                aligned_face = self.sface.alignCrop(frame, face)
                current_emb = self.sface.feature(aligned_face)
                current_emb = current_emb / np.linalg.norm(current_emb)

                # Liveness & Anti-Spoofing analysis
                face_crop = frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                liveness = self.check_liveness(face_crop)

                best_name = "Unknown"
                best_sim = -1.0

                for name, ref_embeddings in self.known_faces:
                    for ref_emb in ref_embeddings:
                        # Cosine similarity
                        sim = float(np.dot(current_emb.flatten(), ref_emb.flatten()))
                        if sim > best_sim:
                            best_sim = sim
                            if sim >= 0.363: # SFace standard cosine threshold
                                best_name = name

                confidence = round(max(0.0, min(100.0, (best_sim + 1.0) * 50.0)), 1)
                display_name = best_name

                recognized.append({
                    "name": display_name,
                    "raw_name": best_name,
                    "bbox": bbox,
                    "confidence": confidence,
                    "score": round(best_sim, 3),
                    "is_live": liveness["is_live"],
                    "liveness_score": liveness["liveness_score"],
                    "liveness_reason": liveness["reason"],
                })
            return recognized

        # 2. InsightFace Engine
        if self.engine == "insightface":
            faces = self.app.get(frame)
            if not faces:
                return []
            recognized = []
            for face in faces:
                emb = face.embedding / np.linalg.norm(face.embedding)
                bbox = face.bbox.astype(int).tolist()
                face_crop = frame[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                liveness = self.check_liveness(face_crop)

                best_name = "Unknown"
                min_dist = 1.0
                for name, ref_embeddings in self.known_faces:
                    for ref_emb in ref_embeddings:
                        dist = 1.0 - float(np.dot(emb, ref_emb))
                        if dist < min_dist and dist < 0.60:
                            min_dist = dist
                            best_name = name

                display_name = best_name

                recognized.append({
                    "name": display_name,
                    "raw_name": best_name,
                    "bbox": bbox,
                    "confidence": round((1.0 - min_dist) * 100, 1),
                    "is_live": liveness["is_live"],
                    "liveness_score": liveness["liveness_score"],
                    "liveness_reason": liveness["reason"],
                })
            return recognized

        # 3. LBPH Classical Fallback
        if self.lbph is not None and self.lbph_names:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            boxes = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.08, minNeighbors=5, minSize=(55, 55)
            )
            recognized_faces = []
            for x, y, bw, bh in boxes:
                prepared = self._prepare_face(gray[y : y + bh, x : x + bw])
                label, distance = self.lbph.predict(prepared)
                name = self.lbph_names.get(label, "Unknown") if distance <= 85 else "Unknown"
                recognized_faces.append({
                    "name": name,
                    "bbox": [int(x), int(y), int(x + bw), int(y + bh)],
                    "confidence": round(max(0.0, 100.0 - distance), 1),
                })
            return recognized_faces

        return []
