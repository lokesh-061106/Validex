"""Object detectors for infrastructure evidence.

Preferred: YOLOv8n exported to ONNX and run with ONNX Runtime (no PyTorch; ~60 MB RAM), so the
backend fits small hosts. Fallback: the ultralytics package with the PyTorch weights.
Both return COCO class counts and an annotated RGB image.
"""

import logging
import os

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

WEIGHTS_DIR = os.path.join(os.path.dirname(__file__), "weights")
ONNX_WEIGHTS = os.path.join(WEIGHTS_DIR, "yolov8n.onnx")

COCO_NAMES = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard",
    "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple",
    "sandwich", "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch",
    "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard",
    "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
    "scissors", "teddy bear", "hair drier", "toothbrush",
]


class OnnxYolo:
    name = "yolov8n-onnx (COCO)"

    def __init__(self, path: str = ONNX_WEIGHTS, size: int = 640):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.session = ort.InferenceSession(path, sess_options=opts, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.size = size

    def _letterbox(self, img: np.ndarray):
        h, w = img.shape[:2]
        r = min(self.size / h, self.size / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
        top, left = (self.size - nh) // 2, (self.size - nw) // 2
        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        canvas[top:top + nh, left:left + nw] = resized
        return canvas, r, left, top

    def detect(self, rgb: np.ndarray, conf: float = 0.3, iou: float = 0.45):
        canvas, r, left, top = self._letterbox(rgb)
        blob = canvas.astype(np.float32).transpose(2, 0, 1)[None] / 255.0
        out = self.session.run(None, {self.input_name: blob})[0][0].T  # (8400, 84)
        scores = out[:, 4:]
        cls = scores.argmax(axis=1)
        best = scores[np.arange(len(scores)), cls]
        keep = best >= conf
        out, cls, best = out[keep], cls[keep], best[keep]
        boxes = []
        for cx, cy, bw, bh in out[:, :4]:
            x0 = (cx - bw / 2 - left) / r
            y0 = (cy - bh / 2 - top) / r
            boxes.append([float(x0), float(y0), float(bw / r), float(bh / r)])
        idx = cv2.dnn.NMSBoxesBatched(boxes, best.tolist(), cls.tolist(), conf, iou) if boxes else []
        counts: dict[str, int] = {}
        annotated = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR).copy()
        for i in np.array(idx).flatten():
            name = COCO_NAMES[int(cls[i])]
            counts[name] = counts.get(name, 0) + 1
            x, y, w, h = (int(v) for v in boxes[i])
            cv2.rectangle(annotated, (x, y), (x + w, y + h), (40, 200, 60), 2)
            cv2.putText(annotated, f"{name} {best[i]:.2f}", (x, max(y - 4, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 200, 60), 1)
        return counts, cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB)


class UltralyticsYolo:
    name = "yolov8n (COCO)"

    def __init__(self, weights_path: str):
        from ultralytics import YOLO

        self.model = YOLO(weights_path)

    def detect(self, rgb: np.ndarray, conf: float = 0.3, iou: float = 0.45):
        result = self.model(rgb, conf=conf, iou=iou, verbose=False)[0]
        counts: dict[str, int] = {}
        for box in result.boxes:
            name = self.model.names[int(box.cls)]
            counts[name] = counts.get(name, 0) + 1
        return counts, result.plot()[:, :, ::-1]


def load_detector(fallback_weights_dir: str):
    """ONNX Runtime first (light), then ultralytics; None when neither is available."""
    if cv2 is not None and os.path.exists(ONNX_WEIGHTS):
        try:
            det = OnnxYolo()
            logger.info("Infrastructure detector: YOLOv8n via ONNX Runtime")
            return det
        except Exception as e:
            logger.info(f"ONNX Runtime detector unavailable ({e})")
    try:
        os.makedirs(fallback_weights_dir, exist_ok=True)
        det = UltralyticsYolo(os.path.join(fallback_weights_dir, "yolov8n.pt"))
        logger.info("Infrastructure detector: YOLOv8n via ultralytics")
        return det
    except Exception as e:
        logger.warning(f"No object detector available ({e}); infrastructure analysis will request manual review.")
        return None
