"""Computer-vision assistance for infrastructure evidence (lab photos and walkthrough videos).

Uses a pre-trained YOLOv8 (COCO) detector. COCO has no "computer" or "fire extinguisher" class,
so equipment is derived from proxy classes (monitor = "tv", "laptop", "keyboard") and anything
the model cannot see is reported as "not detectable - manual check", never guessed.
If the detector is unavailable the module says so and recommends manual review.
Results are advisory: a count below the norm suggests additional evidence or inspection.
"""

import base64
import io
import logging
import os
import tempfile
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False

MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ml_models"))

# Equipment name -> (COCO classes used as evidence, how to combine them)
EQUIPMENT_PROXIES: dict[str, dict[str, Any]] = {
    "computer": {"classes": ["tv", "laptop", "keyboard"], "combine": "max_of_monitor_or_keyboard",
                 "note": "workstations = max(monitors+laptops, keyboards)"},
    "chair": {"classes": ["chair"], "combine": "sum"},
    "table": {"classes": ["dining table"], "combine": "sum"},
    "person": {"classes": ["person"], "combine": "sum"},
}
NOT_DETECTABLE = {"fire_extinguisher", "projector", "smart_board", "lathe", "oscilloscope", "first_aid_kit"}


class InfrastructureReport:
    def __init__(self, status: str, equipment_counts: dict[str, int], raw_counts: dict[str, int],
                 compliance_flags: list[dict[str, Any]], quality: dict[str, Any],
                 annotated_image_base64: str | None, frames_analyzed: int, model: str | None):
        self.status = status  # "analyzed" | "detector_unavailable" | "unreadable"
        self.equipment_counts = equipment_counts
        self.raw_counts = raw_counts
        self.compliance_flags = compliance_flags
        self.quality = quality
        self.annotated_image_base64 = annotated_image_base64
        self.frames_analyzed = frames_analyzed
        self.model = model

    @property
    def needs_manual_review(self) -> bool:
        return self.status != "analyzed" or any(f["status"] != "compliant" for f in self.compliance_flags) or bool(self.quality.get("issues"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "model": self.model,
            "equipment_counts": self.equipment_counts,
            "raw_detections": self.raw_counts,
            "compliance_flags": self.compliance_flags,
            "evidence_quality": self.quality,
            "frames_analyzed": self.frames_analyzed,
            "annotated_image_base64": self.annotated_image_base64,
            "total_detected": sum(self.raw_counts.values()),
            "needs_manual_review": self.needs_manual_review,
            "disclaimer": "Advisory counts from a general-purpose detector; confirm by inspection where flagged.",
        }


class InfrastructureCV:
    def __init__(self):
        self._model = None
        self._initialized = False

    def _get_model(self):
        if not self._initialized:
            self._initialized = True
            from app.ml.detectors import load_detector
            self._model = load_detector(MODEL_DIR)
        return self._model

    @staticmethod
    def is_video(file_bytes: bytes, filename: str = "") -> bool:
        return file_bytes[4:8] == b"ftyp" or filename.lower().endswith((".mp4", ".mov", ".avi", ".webm"))

    @staticmethod
    def extract_keyframes(video_bytes: bytes, every_seconds: float = 1.0, max_frames: int = 12) -> list[np.ndarray]:
        if not HAS_OPENCV:
            return []
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp.write(video_bytes)
            path = tmp.name
        frames = []
        try:
            cap = cv2.VideoCapture(path)
            fps = cap.get(cv2.CAP_PROP_FPS) or 25
            step = max(int(fps * every_seconds), 1)
            idx = 0
            while len(frames) < max_frames:
                ok, frame = cap.read()
                if not ok:
                    break
                if idx % step == 0:
                    frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                idx += 1
            cap.release()
        finally:
            os.unlink(path)
        return frames

    @staticmethod
    def _quality(img: np.ndarray) -> dict[str, Any]:
        issues = []
        if not HAS_OPENCV:
            return {"issues": issues}
        h0, w0 = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        if max(h0, w0) > 1600:  # judge sharpness at a fixed scale and keep memory bounded
            r = 1600 / max(h0, w0)
            gray = cv2.resize(gray, (int(w0 * r), int(h0 * r)), interpolation=cv2.INTER_AREA)
        brightness = float(gray.mean())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        h, w = h0, w0
        if brightness < 50:
            issues.append("Photo is too dark to assess equipment reliably")
        if sharpness < 40:
            issues.append("Photo is blurred; counts may be unreliable")
        if min(h, w) < 400:
            issues.append(f"Low resolution ({w}x{h}); submit at least 1280px wide")
        return {"brightness": round(brightness, 1), "sharpness": round(sharpness, 1), "resolution": [w, h], "issues": issues}

    def analyze(self, file_bytes: bytes, norms: list[dict[str, Any]], filename: str = "") -> InfrastructureReport:
        """norms: [{"object": "computer", "min": 15, "rule_code": "...", "label": "..."}] from the rule engine."""
        if self.is_video(file_bytes, filename):
            frames = self.extract_keyframes(file_bytes)
        else:
            try:
                frames = [np.array(Image.open(io.BytesIO(file_bytes)).convert("RGB"))]
            except Exception:
                frames = []
        if not frames:
            return InfrastructureReport("unreadable", {}, {}, self._flags(norms, None), {"issues": ["File could not be read as an image or video"]}, None, 0, None)

        quality = self._quality(frames[0])
        model = self._get_model()
        if model is None:
            return InfrastructureReport("detector_unavailable", {}, {}, self._flags(norms, None), quality,
                                        _data_uri(frames[0]), len(frames), None)

        raw: dict[str, int] = {}
        best_frame, best_total = None, -1
        for frame in frames:
            counts, annotated = model.detect(frame)
            # Across video keyframes take the max per class to avoid double counting the same item
            for k, v in counts.items():
                raw[k] = max(raw.get(k, 0), v)
            total = sum(counts.values())
            if total > best_total:
                best_total, best_frame = total, annotated

        equipment = self._derive(raw)
        return InfrastructureReport("analyzed", equipment, raw, self._flags(norms, equipment), quality,
                                    _data_uri(best_frame if best_frame is not None else frames[0]), len(frames), model.name)

    @staticmethod
    def _derive(raw: dict[str, int]) -> dict[str, int]:
        monitors = raw.get("tv", 0) + raw.get("laptop", 0)
        return {
            "computer": max(monitors, raw.get("keyboard", 0)),
            "chair": raw.get("chair", 0),
            "table": raw.get("dining table", 0),
            "person": raw.get("person", 0),
        }

    @staticmethod
    def _flags(norms: list[dict[str, Any]], equipment: dict[str, int] | None) -> list[dict[str, Any]]:
        flags = []
        for n in norms:
            obj, required = n["object"], n["min"]
            base = {"equipment": n.get("label") or obj, "object": obj, "required": required, "rule_code": n.get("rule_code")}
            if equipment is None:
                flags.append({**base, "detected": None, "status": "manual_review",
                              "message": "Automated detection unavailable; verify from the photo or during inspection"})
            elif obj in NOT_DETECTABLE or obj not in EQUIPMENT_PROXIES:
                flags.append({**base, "detected": None, "status": "not_detectable",
                              "message": f"'{obj}' is outside the detector's vocabulary; manual check required"})
            else:
                count = equipment.get(obj, 0)
                ok = count >= required
                flags.append({**base, "detected": count, "status": "compliant" if ok else "deficient",
                              "message": f"Detected {count} (norm: at least {required})" if ok
                              else f"Only {count} visible (norm: at least {required}); request additional photos or inspect"})
        return flags


def _data_uri(img: np.ndarray, max_width: int = 1000) -> str:
    pil = Image.fromarray(img)
    if pil.width > max_width:
        pil = pil.resize((max_width, int(pil.height * max_width / pil.width)))
    buf = io.BytesIO()
    pil.convert("RGB").save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


infrastructure_cv = InfrastructureCV()
