"""One lazy, CPU-only inference process, shared by capture and enrollment."""
import multiprocessing as mp
from pathlib import Path
import threading
import time


def rank(features, people, threshold, margin):
    import numpy as np
    if len(features) == 0:
        return {"status": "no_face", "person_id": None, "score": None, "face_count": 0}
    if len(features) > 1:
        return {"status": "ambiguous", "person_id": None, "score": None, "face_count": len(features)}
    query = np.asarray(features[0], dtype=np.float32)
    scores = []
    for person in people:
        vectors = np.asarray(person["vectors"], dtype=np.float32)
        score = float((vectors @ query).max())
        scores.append((score, person["id"]))
    scores.sort(reverse=True)
    best = scores[0][0] if scores else None
    identity, status = None, "unknown"
    if scores and best >= threshold:
        if len(scores) > 1 and best - scores[1][0] < margin:
            status = "ambiguous"
        else:
            identity, status = scores[0][1], "recognized"
    return {"status": status, "person_id": identity, "score": best, "face_count": 1}


def _process(conn, models, threads):
    import cv2
    import numpy as np
    import resource
    import os
    os.nice(10)
    cv2.setNumThreads(threads)
    cv2.ocl.setUseOpenCL(False)
    detector = cv2.FaceDetectorYN.create(str(Path(models) / "face_detection_yunet_2023mar.onnx"), "", (320, 320), 0.8, 0.3, 100)
    recognizer = cv2.FaceRecognizerSF.create(str(Path(models) / "face_recognition_sface_2021dec.onnx"), "")
    conn.send({"ready": True})
    while True:
        try:
            raw = conn.recv()
        except EOFError:
            break
        try:
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            height, width = image.shape[:2]
            scale = min(1.0, 640 / max(width, height))
            preview = cv2.resize(image, (max(1, int(width * scale)), max(1, int(height * scale))))
            detector.setInputSize((preview.shape[1], preview.shape[0]))
            _, faces = detector.detect(preview)
            if faces is not None:
                faces[:, :14] /= scale
            features, warnings = [], []
            for face in [] if faces is None else faces:
                # Small faces may be visible but cannot yield a reliable identity.
                if min(face[2], face[3]) < 60:
                    warnings.append("Face smaller than 60 pixels; use a closer, sharp photo")
                    features.append(None)
                    continue
                aligned = recognizer.alignCrop(image, face)
                if cv2.Laplacian(aligned, cv2.CV_64F).var() < 50:
                    warnings.append("Photo may be blurred")
                vector = recognizer.feature(aligned).flatten()
                norm = np.linalg.norm(vector)
                if not np.isfinite(norm) or norm < 1e-6:
                    raise ValueError("Invalid embedding")
                vector /= norm
                features.append(vector.tolist())
            conn.send({"features": features, "warnings": warnings, "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
        except Exception:
            conn.send({"error": "Image inference failed"})


class Engine:
    def __init__(self, settings):
        self.settings, self.lock = settings, threading.Lock()
        self.process = self.conn = None
        self.peak_rss_kib = 0

    def analyze(self, raw):
        if not self.lock.acquire(timeout=1):
            raise RuntimeError("Recognition engine busy; retry later")
        try:
            start = time.monotonic()
            if self.process is None or not self.process.is_alive():
                self._stop()
                context = mp.get_context("spawn")
                self.conn, child = context.Pipe()
                self.process = context.Process(target=_process, args=(child, self.settings.models, self.settings.opencv_threads), daemon=True)
                self.process.start()
                child.close()
                if not self.conn.poll(self.settings.processing_timeout):
                    self._stop()
                    raise TimeoutError("Recognition initialization deadline exceeded")
                if self.conn.recv() != {"ready": True}:
                    self._stop()
                    raise RuntimeError("Recognition initialization failed")
            self.conn.send(raw)
            remaining = max(0.001, self.settings.processing_timeout - (time.monotonic() - start))
            if not self.conn.poll(remaining):
                self._stop()
                raise TimeoutError("Recognition deadline exceeded; engine terminated")
            result = self.conn.recv()
            if "error" in result:
                raise ValueError(result["error"])
            self.peak_rss_kib = result["peak_rss_kib"]
            result["duration_ms"] = round((time.monotonic() - start) * 1000)
            return result
        except (EOFError, BrokenPipeError) as e:
            self._stop()
            raise RuntimeError("Recognition engine exited") from e
        finally:
            self.lock.release()

    def _stop(self):
        if self.process is not None:
            if self.process.is_alive():
                self.process.terminate()
            self.process.join(timeout=2)
            if self.process.is_alive():
                self.process.kill()
                self.process.join(timeout=2)
        if self.conn is not None:
            self.conn.close()
        self.process = self.conn = None

    def close(self):
        with self.lock:
            self._stop()
