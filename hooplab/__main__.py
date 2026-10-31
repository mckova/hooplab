"""One command to run the whole product: `hooplab --demo` (or `python -m hooplab --demo`)."""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(prog="hooplab", description="Run HoopLab: web app and API in one process.")
    ap.add_argument("--demo", action="store_true", help="load the demo team first if the database has no team")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()
    import uvicorn

    from . import api
    if a.demo and not api.db.q("SELECT id FROM teams LIMIT 1"):
        api.seed(api.db, video_dir=str(api.DATA_DIR / "videos"))
        print("Demo team loaded.")
    print(f"HoopLab: http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{a.port}")
    uvicorn.run(api.app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
