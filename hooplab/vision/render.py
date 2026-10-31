"""Render a track file to an MP4 (Pillow + ffmpeg). Used to give the demo team
real, clickable game film generated from the same tracks the analyser reads."""
from __future__ import annotations

import shutil
import subprocess

# Top-down tracking view in the app's palette: dark floor, hairline court, players as numbered discs.
TEAM_COLORS = {1: (242, 140, 40), 2: (106, 168, 232), None: (150, 158, 168)}
FLOOR, COURT, LINE, INK = (14, 16, 19), (24, 28, 34), (70, 79, 92), (233, 236, 239)


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
        img = Image.new("RGB", (w, h), FLOOR)
        d = ImageDraw.Draw(img)
        s = lambda p: (p[0] * scale, p[1] * scale)  # noqa: E731
        if court:
            d.polygon([s(p) for p in court], fill=COURT, outline=LINE, width=2)
            (x0, y0), (x1, y1) = s(court[0]), s(court[2])
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            d.line([(mx, y0), (mx, y1)], fill=LINE, width=2)
            r = (y1 - y0) * 0.12
            d.ellipse([mx - r, my - r, mx + r, my + r], outline=LINE, width=2)
            px, py = (x1 - x0) / 28.0, (y1 - y0) / 15.0           # pixels per metre (FIBA 28 x 15)
            for end, sgn in ((x0, 1), (x1, -1)):
                kx = end + sgn * 5.8 * px
                d.rectangle([min(end, kx), my - 2.45 * py, max(end, kx), my + 2.45 * py], outline=LINE, width=2)
                hx = end + sgn * 1.575 * px
                a = 6.75 * px
                start, stop = (-78, 78) if sgn == 1 else (102, 258)
                d.arc([hx - a, my - 6.75 * py, hx + a, my + 6.75 * py], start, stop, fill=LINE, width=2)
        if fr.get("hoop"):
            hx1, hy1, hx2, hy2 = [v * scale for v in fr["hoop"]]
            rc = (hx1 + hx2) / 2
            ry = my if court else (hy1 + hy2) / 2     # top-down view: the rim sits over its floor point
            rr = (hx2 - hx1) / 2
            d.ellipse([rc - rr, ry - rr, rc + rr, ry + rr], outline=(229, 103, 95), width=2)
            d.line([(rc + rr + 3, ry - 14), (rc + rr + 3, ry + 14)], fill=INK, width=3)
        rad = max(7, int(11 * scale * 2))
        for tid, p in (fr.get("players") or {}).items():
            x1, y1, x2, y2 = [v * scale for v in p["bbox"]]
            cx, cy = (x1 + x2) / 2, y2 - rad
            col = TEAM_COLORS.get(p.get("team"), TEAM_COLORS[None])
            d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=col, outline=FLOOR, width=2)
            d.text((cx, cy), str(labels.get(str(tid), tid)).lstrip("#"), fill=FLOOR, anchor="mm")
        if fr.get("ball"):
            bx1, by1, bx2, by2 = [v * scale for v in fr["ball"]]
            bc, br = ((bx1 + bx2) / 2, (by1 + by2) / 2), max(4, (bx2 - bx1) / 2 + 1)
            d.ellipse([bc[0] - br, bc[1] - br, bc[0] + br, bc[1] + br], fill=(255, 176, 102), outline=FLOOR, width=1)
        d.text((10, 8), f"{i / fps:4.1f}s", fill=(111, 120, 132))
        proc.stdin.write(img.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out_path
