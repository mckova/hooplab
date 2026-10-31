"""Render a track file to an MP4 (Pillow + ffmpeg). Used to give the demo team
real, clickable game film generated from the same tracks the analyser reads."""
from __future__ import annotations

import shutil
import subprocess

# Top-down tracking view in the app's night palette: dark floor, fine light lines,
# our team as solid light discs, the opponent as court-blue rings, orange only for the ball.
US, US_INK = (238, 240, 244), (20, 23, 28)
THEM = (127, 157, 230)
GREY = (140, 145, 150)
FLOOR, COURT, LINE, INK = (14, 16, 19), (20, 23, 28), (78, 81, 87), (20, 23, 28)
BALL = (240, 124, 44)
SS = 2  # draw at twice the size and downsample, so lines and discs are anti-aliased


def render_mp4(tracks: dict, out_path: str, scale: float = 1.0, size=(1320, 800),
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
    from PIL import ImageFont
    scale = scale * SS
    rad = max(7 * SS, int(11 * scale * 2))
    try:
        font = ImageFont.load_default(size=int(rad * .95))
    except TypeError:                              # Pillow < 10.1
        font = ImageFont.load_default()
    lw = 2 * SS
    s = lambda p: (p[0] * scale, p[1] * scale)  # noqa: E731
    base = Image.new("RGB", (w * SS, h * SS), FLOOR)
    d = ImageDraw.Draw(base)
    if court:  # the court never moves: draw it once
        d.polygon([s(p) for p in court], fill=COURT, outline=LINE, width=lw)
        (x0, y0), (x1, y1) = s(court[0]), s(court[2])
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        d.line([(mx, y0), (mx, y1)], fill=LINE, width=lw)
        r = (y1 - y0) * 0.12
        d.ellipse([mx - r, my - r, mx + r, my + r], outline=LINE, width=lw)
        px, py = (x1 - x0) / 28.0, (y1 - y0) / 15.0           # pixels per metre (FIBA 28 x 15)
        for end, sgn in ((x0, 1), (x1, -1)):
            kx = end + sgn * 5.8 * px
            d.rectangle([min(end, kx), my - 2.45 * py, max(end, kx), my + 2.45 * py], outline=LINE, width=lw)
            hx = end + sgn * 1.575 * px
            a = 6.75 * px
            start, stop = (-78, 78) if sgn == 1 else (102, 258)
            d.arc([hx - a, my - 6.75 * py, hx + a, my + 6.75 * py], start, stop, fill=LINE, width=lw)
    for i, fr in enumerate(tracks["frames"]):
        img = base.copy()
        d = ImageDraw.Draw(img)
        if fr.get("hoop"):
            hx1, hy1, hx2, hy2 = [v * scale for v in fr["hoop"]]
            rc = (hx1 + hx2) / 2
            ry = my if court else (hy1 + hy2) / 2     # top-down view: the rim sits over its floor point
            rr = (hx2 - hx1) / 2
            d.ellipse([rc - rr, ry - rr, rc + rr, ry + rr], outline=US, width=lw)
            bx = rc + rr + 3 * SS if rc > w * SS / 2 else rc - rr - 3 * SS
            d.line([(bx, ry - 14 * SS), (bx, ry + 14 * SS)], fill=US, width=3 * SS)
        for tid, p in (fr.get("players") or {}).items():
            x1, y1, x2, y2 = [v * scale for v in p["bbox"]]
            cx, cy = (x1 + x2) / 2, y2 - rad
            team, box = p.get("team"), [cx - rad, cy - rad, cx + rad, cy + rad]
            if team == 1:
                d.ellipse(box, fill=US)
                ink = US_INK
            else:
                ink = THEM if team == 2 else GREY
                d.ellipse(box, fill=COURT, outline=ink, width=lw)
            d.text((cx, cy), str(labels.get(str(tid), tid)).lstrip("#"), fill=ink, anchor="mm", font=font)
        if fr.get("ball"):
            bx1, by1, bx2, by2 = [v * scale for v in fr["ball"]]
            bc, br = ((bx1 + bx2) / 2, (by1 + by2) / 2), max(4 * SS, (bx2 - bx1) / 2 + SS)
            d.ellipse([bc[0] - br, bc[1] - br, bc[0] + br, bc[1] + br], fill=BALL, outline=INK, width=SS)
        proc.stdin.write(img.reduce(SS).tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return out_path
