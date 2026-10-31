# Track file format

The contract between any detector/tracker and HoopLab's analytics. One JSON
object per video:

```json
{
  "fps": 25,
  "court_points": {
    "image": [[100, 100], [1220, 100], [1220, 700], [100, 700]],
    "court": [[0, 0], [28, 0], [28, 15], [0, 15]]
  },
  "roster_map": { "7": 12, "3": 15 },
  "frames": [
    {
      "players": { "7": { "bbox": [x1, y1, x2, y2], "team": 1 } },
      "ball": [x1, y1, x2, y2],
      "hoop": [x1, y1, x2, y2]
    }
  ]
}
```

| Field | Required | Meaning |
|---|---|---|
| `fps` | yes | Frames per second of the `frames` list (after any stride) |
| `frames[].players` | yes | Track id → box in pixels and team label (1 or 2) |
| `frames[].ball` | for possession/passes | Best ball box, or `null` |
| `frames[].hoop` | for shots | Hoop/rim box, or `null` |
| `court_points` | for zones, speed, sprint-backs | ≥4 image points and their court position in metres (FIBA 28×15, origin top-left) |
| `roster_map` | to credit your players | Track id → HoopLab player id (set once per video by the coach, e.g. from jersey numbers) |

Events credited to tracks that are not in `roster_map` but belong to the other
team are stored as **opponent scouting** when the session has an opponent.

Produce one with `YoloTrackBackend().process(video_path, court_points, roster_map)`
(`pip install hooplab[vision]`), or with `hooplab.vision.synth` for tests.
