---
name: livestream
description: YouTube Livestream Manager — Create broadcasts, manage stream keys, push RTMP with FFmpeg
---

# Livestream Extension

Manages YouTube livestreams: create broadcasts, generate stream keys, push
RTMP streams via FFmpeg, and schedule automated streaming sessions.

## Dependencies

- **auth_manager** extension (for Google OAuth tokens with `youtube` scope)
- **FFmpeg** installed and in system PATH

## Usage from Other Extensions

```python
from extension import livestream_manager

# List YouTube credentials
creds = livestream_manager.list_youtube_credentials()

# Create a broadcast (returns stream key)
result = livestream_manager.create_broadcast(
    token_id="cred_abc123_xyz",
    title="My Stream",
    privacy="unlisted"
)

# Start FFmpeg push
ffmpeg = livestream_manager.start_ffmpeg(
    stream_key=result["broadcast"]["stream_key"],
    preset="file",
    input_source="/path/to/video.mp4"
)

# One-click go live
result = livestream_manager.auto_go_live(
    token_id="cred_abc123_xyz",
    title="Quick Stream",
    input_source="/path/to/video.mp4",
    preset="file_loop"
)
```

## API Endpoints

### Broadcasts
- `GET /api/v1/livestream/credentials` — List YouTube credentials
- `GET /api/v1/livestream/broadcasts` — List broadcasts
- `POST /api/v1/livestream/broadcasts` — Create broadcast + stream
- `DELETE /api/v1/livestream/broadcasts/{id}` — Delete broadcast
- `POST /api/v1/livestream/broadcasts/{id}/transition` — Transition state

### FFmpeg
- `POST /api/v1/livestream/ffmpeg/start` — Start FFmpeg push
- `POST /api/v1/livestream/ffmpeg/stop/{session}` — Stop FFmpeg
- `GET /api/v1/livestream/ffmpeg/sessions` — List sessions
- `GET /api/v1/livestream/ffmpeg/log/{session}` — Get FFmpeg log

### Scheduling
- `GET /api/v1/livestream/schedules` — List schedules
- `POST /api/v1/livestream/schedules` — Add schedule
- `DELETE /api/v1/livestream/schedules/{id}` — Remove schedule

### Utilities
- `POST /api/v1/livestream/auto-live` — One-click go live
- `GET /api/v1/livestream/ffmpeg-check` — Check FFmpeg
- `GET /api/v1/livestream/presets` — FFmpeg presets

## FFmpeg Presets

| Preset | Description |
|--------|-------------|
| `file` | Stream a video file |
| `file_loop` | Loop a video file (24/7) |
| `camera_win` | Webcam + mic (Windows) |
| `screen_win` | Screen capture (Windows) |
| `screen_linux` | Screen capture (Linux/X11) |
| `custom` | Custom FFmpeg command |
