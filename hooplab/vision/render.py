"""Render a track file to an MP4 (Pillow + ffmpeg). Used to give the demo team
real, clickable game film generated from the same tracks the analyser reads."""
from __future__ import annotations

import shutil
import subprocess

TEAM_COLORS = {1: (242, 140, 40), 2: (76, 155, 232), None: (160, 160, 160)}


def render_mp4(tracks: dict, out_path: str, scale: float = 0.5, size=(1320, 800),
               labels: dict | None = None) -> str:
    from PIL import Image, ImageDraw

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found")
    w, h = int(size[0] * scale) // 2 * 2, int(size[1] * scale) // 2 * 2
    fps = tracks.get("fps", 25)
    proc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                             "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                             "-movflags", "+faststart", "-crf", "28", out_path], stdin=subprocess.PIPE)
    court = tracks.get("court_points", {}).get("image")
    labels = labels or {}
    for i, fr in enumerate(tracks["frames"]):
        img = Image.new("RGB", (w, h), (196, 154, 108))
        d = ImageDraw.Draw(img)
        s = lambda p: (p[0] * scale, p[1] * scale)  # noqa: E731
        if court:
            d.polygon([s(p) for p in court], outline=(255, 255, 255), width=2)
            (x0, y0), (x1, y1) = s(court[0]), s(court[2])
            d.line([((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)], fill=(255, 255, 255), width=2)
        if fr.get("hoop"):
            hx1, hy1, hx2, hy2 = [v * scale for v in fr["hoop"]]
            d.rectangle([hx1, hy1, hx2, hy2], outline=(230, 60, 40), width=2)
            d.line([(hx2 + 2, hy1 - 14), (hx2 + 2, hy2 + 6)], fill=(250, 250, 250), width=3)
        for tid, p in (fr.get("players") or {}).items():
            x1, y1, x2, y2 = [v * scale for v in p["bbox"]]
            col = TEAM_COLORS.get(p.get("team"), TEAM_COLORS[None])
            d.rounded_rectangle([x1, y1, x2, y2], radius=4, fill=col, outline=(30, 30, 30))
            d.text((x1 + 2, y1 + 2), str(labels.get(str(tid), tid)), fill=(0, 0, 0))
        if fr.get("ball"):
            bx1, by1, bx2, by2 = [v * scale for v in fr["ball"]]
            d.ellipse([bx1 - 1, by1 - 1, bx2 + 1, by2 + 1], fill=(235, 100, 20), outline=(0, 0, 0))
        d.text((6, 4), f"{i / fps:5.1f}s", fill=(20, 20, 20))
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out_path
