"""Video -> track-file backends.

`YoloTrackBackend` turns a video into the track format consumed by
`analysis.analyze`. It needs the optional `vision` extra
(`pip install hooplab[vision]`: ultralytics + opencv). Without it, the platform
still works from track files produced elsewhere or from tagged event logs, and
the API reports that video processing is unavailable instead of failing.

Detection weights:
* players + ball: any COCO YOLO model (classes `person`, `sports ball`);
* hoop: COCO has no hoop class, so shot detection needs a model fine-tuned with
  a `hoop`/`rim` class (set HOOPLAB_YOLO_WEIGHTS). Without it the pipeline still
  yields possession, passes, turnovers, steals and movement.
"""
from __future__ import annotations

import os

import numpy as np


def vision_available() -> bool:
    try:
        import cv2  # noqa: F401
        import ultralytics  # noqa: F401
        return True
    except ImportError:
        return False


def kmeans2(colors: np.ndarray, iters: int = 20, seed: int = 0) -> np.ndarray:
    """Tiny 2-means for jersey colours (Lab or RGB rows) -> labels 0/1."""
    rng = np.random.default_rng(seed)
    c = colors[rng.choice(len(colors), 2, replace=False)].astype(float)
    labels = np.zeros(len(colors), int)
    for _ in range(iters):
        d = ((colors[:, None, :] - c[None, :, :]) ** 2).sum(-1)
        labels = d.argmin(1)
        for k in range(2):
            if (labels == k).any():
                c[k] = colors[labels == k].mean(0)
    return labels


def torso_color(frame, box) -> np.ndarray:
    x1, y1, x2, y2 = [int(v) for v in box]
    h, w = y2 - y1, x2 - x1
    crop = frame[y1 + h // 5: y1 + h // 2, x1 + w // 4: x2 - w // 4]
    if crop.size == 0:
        return np.zeros(3)
    return crop.reshape(-1, 3).astype(float).mean(0)


class YoloTrackBackend:
    def __init__(self, weights: str | None = None, stride: int = 1, conf: float = 0.25):
        self.weights = weights or os.environ.get("HOOPLAB_YOLO_WEIGHTS", "yolo11n.pt")
        self.stride = stride
        self.conf = conf

    def process(self, video_path: str, court_points: dict | None = None,
                roster_map: dict | None = None) -> dict:
        if not vision_available():
            raise RuntimeError("video processing needs `pip install hooplab[vision]`")
        import cv2
        from ultralytics import YOLO

        model = YOLO(self.weights)
        names = {int(k): v.lower() for k, v in model.names.items()}
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frames, colors, color_owner = [], [], []
        idx = 0
        while True:
            ok, img = cap.read()
            if not ok:
                break
            idx += 1
            if (idx - 1) % self.stride:
                continue
            res = model.track(img, persist=True, conf=self.conf, verbose=False)[0]
            fr = {"players": {}, "ball": None, "hoop": None}
            best_ball = 0.0
            for box, cls, conf, tid in zip(res.boxes.xyxy.tolist(), res.boxes.cls.tolist(),
                                           res.boxes.conf.tolist(),
                                           (res.boxes.id.tolist() if res.boxes.id is not None
                                            else [None] * len(res.boxes))):
                name = names.get(int(cls), "")
                if name in ("person", "player") and tid is not None:
                    fr["players"][str(int(tid))] = {"bbox": [round(v, 1) for v in box]}
                    colors.append(torso_color(img, box))
                    color_owner.append((len(frames), str(int(tid))))
                elif name in ("sports ball", "ball", "basketball") and conf > best_ball:
                    fr["ball"], best_ball = [round(v, 1) for v in box], conf
                elif name in ("hoop", "rim", "basket"):
                    fr["hoop"] = [round(v, 1) for v in box]
            frames.append(fr)
        cap.release()
        # team assignment: majority 2-means label per track id
        if len(colors) >= 2:
            labels = kmeans2(np.asarray(colors))
            votes: dict[str, list[int]] = {}
            for (fi, tid), lab in zip(color_owner, labels):
                votes.setdefault(tid, []).append(int(lab))
            team = {t: 1 + int(round(np.mean(v))) for t, v in votes.items()}
            for fr in frames:
                for t, p in fr["players"].items():
                    p["team"] = team.get(t)
        out = {"fps": fps / self.stride, "frames": frames, "roster_map": roster_map or {}}
        if court_points:
            out["court_points"] = court_points
        return out
