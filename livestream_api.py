"""
Livestream Extension — FastAPI routes.
YouTube Livestream management and FFmpeg RTMP push control.
Pattern mirrors sheets_api.py: import auth_manager directly.
"""
import os
import uuid
import json
import logging
import shutil
import subprocess
import threading
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# ── Import auth_manager exactly like sheets_api.py ──────────────────
try:
    from tubecli.extensions.auth_manager.extension import auth_manager as am
except ImportError:
    from zhiying.extensions.auth_manager.extension import auth_manager as am

router = APIRouter(prefix="/api/v1/livestream", tags=["livestream"])
logger = logging.getLogger("LivestreamAPI")

# ── Data paths ────────────────────────────────────────────────────────
try:
    from tubecli.config import DATA_DIR
except ImportError:
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

LIVESTREAM_DATA_DIR = os.path.join(str(DATA_DIR), "livestream")
LIVESTREAM_DATA_FILE = os.path.join(LIVESTREAM_DATA_DIR, "livestream_data.json")
SCHEDULES_FILE = os.path.join(LIVESTREAM_DATA_DIR, "schedules.json")
YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# ── FFmpeg presets ────────────────────────────────────────────────────
FFMPEG_PRESETS = {
    "file": {
        "label": "📁 File → RTMP",
        "description": "Stream a video file to YouTube",
        "template": '-re -i "{input}" -c:v libx264 -preset veryfast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -ar 44100 -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "4500k", "bufsize": "9000k", "gop": "60"},
    },
    "file_loop": {
        "label": "🔁 Loop File → RTMP",
        "description": "Loop a video file continuously (24/7 stream)",
        "template": '-stream_loop -1 -re -i "{input}" -c:v libx264 -preset veryfast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -ar 44100 -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "4500k", "bufsize": "9000k", "gop": "60"},
    },
    "camera_win": {
        "label": "📷 Camera → RTMP (Windows)",
        "description": "Stream from webcam + microphone",
        "template": '-f dshow -i video="{camera}":audio="{mic}" -c:v libx264 -preset veryfast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -ar 44100 -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "4500k", "bufsize": "9000k", "gop": "60", "camera": "Integrated Camera", "mic": "Microphone"},
    },
    "screen_win": {
        "label": "🖥️ Screen → RTMP (Windows GDI)",
        "description": "Stream desktop screen capture (GDI — may show black for GPU apps)",
        "template": '-f gdigrab -draw_mouse {draw_mouse} -framerate {fps} -i desktop -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -c:v libx264 -preset ultrafast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -shortest -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "3000k", "bufsize": "6000k", "gop": "60", "fps": "30", "draw_mouse": "1"},
    },
    "screen_win_dd": {
        "label": "🖥️ Screen → RTMP (Windows DXGI ✅)",
        "description": "Stream desktop via DirectX Desktop Duplication — fixes black screen for GPU-accelerated apps (Chrome, OBS, games, etc.)",
        "template": '-init_hw_device d3d11va=d3d11 -filter_complex "ddagrab=output_idx={monitor}:draw_mouse={draw_mouse}:framerate={fps},hwdownload,format=bgra,format=yuv420p[v];anullsrc=channel_layout=stereo:sample_rate=44100[a]" -map "[v]" -map "[a]" -c:v libx264 -preset ultrafast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -g {gop} -c:a aac -b:a 128k -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "3000k", "bufsize": "6000k", "gop": "60", "fps": "30", "monitor": "0", "draw_mouse": "1"},
    },
    "screen_linux": {
        "label": "🖥️ Screen → RTMP (Linux)",
        "description": "Stream desktop screen capture (X11)",
        "template": '-f x11grab -framerate {fps} -video_size {resolution} -i :0.0 -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -c:v libx264 -preset ultrafast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -shortest -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "3000k", "bufsize": "6000k", "gop": "60", "fps": "30", "resolution": "1920x1080"},
    },
    "custom": {
        "label": "⚙️ Custom Command",
        "description": "Write your own FFmpeg command",
        "template": '{custom_cmd}',
        "defaults": {},
    },
    "advanced_scene": {
        "label": "✨ Advanced Scene (Layers)",
        "description": "Composite multiple windows and files dynamically (uses DXGI capture — no black screen)",
        "template": "{custom_cmd}",
        "defaults": {"fps": "30", "bitrate": "4500k", "bufsize": "9000k", "gop": "60"},
    },
}

# ── In-memory FFmpeg sessions (per server process) ────────────────────
_ffmpeg_sessions: Dict[str, dict] = {}


# ── Data helpers ──────────────────────────────────────────────────────

def _load_data() -> dict:
    os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
    if os.path.exists(LIVESTREAM_DATA_FILE):
        try:
            with open(LIVESTREAM_DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"broadcasts": {}}


def _save_data(data: dict):
    os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
    with open(LIVESTREAM_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _load_schedules() -> list:
    if not os.path.exists(SCHEDULES_FILE):
        return []
    try:
        with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_schedules(schedules: list):
    os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
    with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
        json.dump(schedules, f, indent=2, ensure_ascii=False)


# ── Auth helpers — same as sheets_api.py ─────────────────────────────

def _get_token(token_id: str) -> Optional[str]:
    """Get active access token via auth_manager (auto-refresh)."""
    return am.get_active_token(token_id)


def _yt_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ── Request models ────────────────────────────────────────────────────

class CreateBroadcastRequest(BaseModel):
    token_id: str
    title: str
    description: str = ""
    privacy: str = "unlisted"
    scheduled_start: str = ""
    resolution: str = "1080p"
    frame_rate: str = "30fps"


class TransitionRequest(BaseModel):
    token_id: str
    target_status: str


class StartFFmpegRequest(BaseModel):
    stream_key: str
    preset: str = "file"
    input_source: str = ""
    custom_args: Optional[Dict] = None
    broadcast_id: str = ""


class AutoLiveRequest(BaseModel):
    token_id: str
    title: str
    description: str = ""
    privacy: str = "unlisted"
    input_source: str = ""
    preset: str = "file"
    ffmpeg_args: Optional[Dict] = None
    resolution: str = "1080p"
    frame_rate: str = "30fps"


class AddScheduleRequest(BaseModel):
    token_id: str
    title: str
    description: str = ""
    privacy: str = "unlisted"
    run_at: str
    input_source: str = ""
    preset: str = "file"
    ffmpeg_args: Optional[Dict] = None
    resolution: str = "1080p"
    frame_rate: str = "30fps"


# ══════════════════════════════════════════════════════════════════════
# CREDENTIALS ENDPOINT — Same pattern as sheets_api.py lines 52-55
# ══════════════════════════════════════════════════════════════════════

@router.get("/credentials")
async def api_list_youtube_credentials():
    """List auth tokens that have YouTube scope — mirrors sheets_api.py."""
    tokens = [
        t for t in am.list_tokens("google")
        if any("youtube" in s for s in t.get("scopes", []))
    ]
    return {
        "credentials": [
            {
                "token_id": t["token_id"],
                "credential_name": t.get("credential_name", "Google"),
                "authorized_email": t.get("authorized_email", ""),
                "provider": t.get("provider", "google"),
                "status": t.get("status", "active"),
            }
            for t in tokens
        ]
    }


# ══════════════════════════════════════════════════════════════════════
# BROADCASTS
# ══════════════════════════════════════════════════════════════════════

@router.get("/broadcasts")
async def api_list_broadcasts(token_id: str = "", include_youtube: bool = False):
    """List all local broadcasts."""
    data = _load_data()
    broadcasts = list(data.get("broadcasts", {}).values())
    # Enrich with live FFmpeg status
    for b in broadcasts:
        bid = b.get("broadcast_id", "")
        for sid, sess in _ffmpeg_sessions.items():
            if sess.get("broadcast_id") == bid:
                proc = sess.get("process")
                b["ffmpeg_running"] = proc is not None and proc.poll() is None
                b["ffmpeg_session_id"] = sid
                break
    return {"broadcasts": broadcasts}


@router.post("/broadcasts")
async def api_create_broadcast(req: CreateBroadcastRequest):
    """Create a YouTube broadcast + live stream, bind them."""
    import requests as http

    token = _get_token(req.token_id)
    if not token:
        raise HTTPException(401, "No valid YouTube token. Please authorize in Auth Manager.")

    headers = _yt_headers(token)
    start_time = req.scheduled_start or (datetime.utcnow() + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # 1. Create liveBroadcast
    try:
        resp = http.post(
            f"{YT_API_BASE}/liveBroadcasts?part=snippet,status,contentDetails",
            headers=headers,
            json={
                "snippet": {"title": req.title, "description": req.description, "scheduledStartTime": start_time},
                "status": {"privacyStatus": req.privacy, "selfDeclaredMadeForKids": False},
                "contentDetails": {"enableAutoStart": True, "enableAutoStop": True, "monitorStream": {"enableMonitorStream": False}},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"Create broadcast failed: {resp.json().get('error', {}).get('message', resp.text[:200])}")
        broadcast_id = resp.json()["id"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Broadcast API error: {str(e)}")

    # 2. Create liveStream
    try:
        resp = http.post(
            f"{YT_API_BASE}/liveStreams?part=snippet,cdn",
            headers=headers,
            json={
                "snippet": {"title": f"{req.title} - Stream"},
                "cdn": {"frameRate": req.frame_rate, "ingestionType": "rtmp", "resolution": req.resolution},
            },
            timeout=30,
        )
        if resp.status_code != 200:
            raise HTTPException(400, f"Create stream failed: {resp.json().get('error', {}).get('message', resp.text[:200])}")
        stream_data = resp.json()
        stream_id = stream_data["id"]
        stream_key = stream_data["cdn"]["ingestionInfo"]["streamName"]
        ingestion_url = stream_data["cdn"]["ingestionInfo"]["ingestionAddress"]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Stream API error: {str(e)}")

    # 3. Bind
    try:
        http.post(
            f"{YT_API_BASE}/liveBroadcasts/bind?id={broadcast_id}&part=id,contentDetails&streamId={stream_id}",
            headers=headers, timeout=30,
        )
    except Exception as e:
        logger.warning(f"Bind warning: {e}")

    # 4. Save locally
    broadcast = {
        "broadcast_id": broadcast_id,
        "stream_id": stream_id,
        "title": req.title,
        "description": req.description,
        "privacy": req.privacy,
        "stream_key": stream_key,
        "ingestion_url": ingestion_url,
        "rtmp_url": f"{ingestion_url}/{stream_key}",
        "token_id": req.token_id,
        "resolution": req.resolution,
        "frame_rate": req.frame_rate,
        "status": "ready",
        "created_at": datetime.now().isoformat(),
        "scheduled_start": start_time,
    }
    data = _load_data()
    data.setdefault("broadcasts", {})[broadcast_id] = broadcast
    _save_data(data)

    return {"status": "success", "broadcast": broadcast}


@router.get("/broadcasts/{broadcast_id}")
async def api_get_broadcast(broadcast_id: str):
    data = _load_data()
    b = data.get("broadcasts", {}).get(broadcast_id)
    if not b:
        raise HTTPException(404, f"Broadcast '{broadcast_id}' not found")
    return {"broadcast": b}


@router.delete("/broadcasts/{broadcast_id}")
async def api_delete_broadcast(broadcast_id: str, token_id: str = ""):
    """Delete broadcast locally and optionally from YouTube."""
    import requests as http

    # Stop any running FFmpeg for this broadcast
    for sid, sess in list(_ffmpeg_sessions.items()):
        if sess.get("broadcast_id") == broadcast_id:
            _stop_ffmpeg_session(sid)

    if token_id:
        token = _get_token(token_id)
        if token:
            try:
                http.delete(f"{YT_API_BASE}/liveBroadcasts?id={broadcast_id}", headers=_yt_headers(token), timeout=15)
            except Exception:
                pass

    data = _load_data()
    if broadcast_id in data.get("broadcasts", {}):
        del data["broadcasts"][broadcast_id]
        _save_data(data)

    return {"status": "success", "message": f"Broadcast '{broadcast_id}' deleted."}


@router.post("/broadcasts/{broadcast_id}/transition")
async def api_transition_broadcast(broadcast_id: str, req: TransitionRequest):
    """Transition broadcast: testing → live → complete."""
    import requests as http

    token = _get_token(req.token_id)
    if not token:
        raise HTTPException(401, "No valid token")

    resp = http.post(
        f"{YT_API_BASE}/liveBroadcasts/transition?broadcastStatus={req.target_status}&id={broadcast_id}&part=status",
        headers=_yt_headers(token), timeout=30,
    )
    if resp.status_code != 200:
        raise HTTPException(400, f"Transition failed: {resp.json().get('error', {}).get('message', resp.text[:200])}")

    data = _load_data()
    if broadcast_id in data.get("broadcasts", {}):
        data["broadcasts"][broadcast_id]["status"] = req.target_status
        _save_data(data)

    return {"status": "success", "message": f"Broadcast transitioned to '{req.target_status}'."}


# ══════════════════════════════════════════════════════════════════════
# FFMPEG SESSIONS
# ══════════════════════════════════════════════════════════════════════

def _stop_ffmpeg_session(session_id: str):
    sess = _ffmpeg_sessions.get(session_id)
    if not sess:
        return
    proc = sess.get("process")
    if proc and proc.poll() is None:
        try:
            proc.stdin.write(b"q")
            proc.stdin.flush()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                proc.kill()
    sess["status"] = "stopped"
    sess["stopped_at"] = datetime.now().isoformat()
    try:
        if sess.get("log_fh"):
            sess["log_fh"].close()
    except Exception:
        pass


def _monitor_ffmpeg(session_id: str):
    sess = _ffmpeg_sessions.get(session_id)
    if not sess:
        return
    proc = sess.get("process")
    if proc:
        proc.wait()
        sess["status"] = "stopped"
        sess["exit_code"] = proc.returncode
        sess["stopped_at"] = datetime.now().isoformat()
        try:
            if sess.get("log_fh"):
                sess["log_fh"].close()
        except Exception:
            pass
        # Update broadcast status
        bid = sess.get("broadcast_id", "")
        if bid:
            data = _load_data()
            if bid in data.get("broadcasts", {}):
                data["broadcasts"][bid]["status"] = "stopped"
                _save_data(data)


@router.post("/ffmpeg/start")
async def api_start_ffmpeg(req: StartFFmpegRequest):
    """Start FFmpeg RTMP push process."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise HTTPException(400, "FFmpeg not found in PATH. Install FFmpeg first.")

    preset_cfg = FFMPEG_PRESETS.get(req.preset)
    if not preset_cfg:
        raise HTTPException(400, f"Unknown preset '{req.preset}'. Available: {list(FFMPEG_PRESETS.keys())}")

    params = {**preset_cfg.get("defaults", {}), **(req.custom_args or {})}
    params["key"] = req.stream_key
    params["input"] = req.input_source

    if req.preset == "advanced_scene":
        # Dynamic filter builder — uses DXGI ddagrab to avoid black screen on GPU-accel apps
        layers = params.get("layers", [])
        if not layers:
            raise HTTPException(400, "Advanced Scene requires at least one layer in custom_args.layers")
        
        canvas_w = int(req.custom_args.get("canvas_w", 1920))
        canvas_h = int(req.custom_args.get("canvas_h", 1080))
        fps = params.get("fps", 30)
        
        # ── Strategy: Use ddagrab to capture the ENTIRE desktop once, then crop ──
        # This avoids the gdigrab black-screen issue entirely.
        # ddagrab captures the composited desktop output (including GPU-rendered windows).
        # We crop regions from the full desktop screenshot to create "layers".
        #
        # For file-type layers, we use regular -i input.
        
        has_window_layers = any(l.get("type", "window") == "window" for l in layers)
        file_layers = [l for l in layers if l.get("type") != "window"]
        window_layers = [l for l in layers if l.get("type", "window") == "window"]
        
        inputs = []
        filter_parts = []
        
        if has_window_layers:
            # Use ddagrab as the primary desktop capture source (input [0])
            # This captures the full composited desktop — no black screen
            inputs.append(f'-init_hw_device d3d11va=d3d11')
            # We will generate ddagrab as a filter source, not as an input
            # So it becomes part of the filter_complex
        
        # Add a black canvas as base layer
        inputs.append(f'-f lavfi -i color=c=black:s={canvas_w}x{canvas_h}:r={fps}:d=86400')
        # Add silent audio
        inputs.append('-f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100')
        
        # Track input index (0=canvas color, 1=audio, file inputs start at 2)
        file_input_idx = 2
        file_idx_map = {}  # layer index -> ffmpeg input index
        
        for i, layer in enumerate(layers):
            ltype = layer.get("type", "window")
            if ltype != "window":
                src = layer.get("source", "")
                inputs.append(f'-re -i "{src}"')
                file_idx_map[i] = file_input_idx
                file_input_idx += 1
        
        # Build filter_complex:
        # 1. ddagrab captures full desktop → hwdownload → format → [desktop]
        # 2. For each window layer, crop from [desktop]
        # 3. For each file layer, scale from its input
        # 4. Overlay all onto the canvas
        
        if has_window_layers:
            filter_parts.append(
                f"ddagrab=output_idx=0:draw_mouse=1:framerate={fps},hwdownload,format=bgra,format=yuv420p[desktop]"
            )
        
        layer_labels = []  # list of filter labels per layer in order
        
        for i, layer in enumerate(layers):
            ltype = layer.get("type", "window")
            w = layer.get("w", canvas_w)
            h = layer.get("h", canvas_h)
            x = layer.get("x", 0)
            y = layer.get("y", 0)
            
            if ltype == "window":
                # Crop region from the full desktop capture
                # Note: x,y here is where the layer goes on the canvas,
                # but the source needs a crop position on the desktop.
                # Since we're compositing, we crop the desktop at (x, y) with size (w, h)
                # This grabs the region of the desktop where the window is expected.
                label = f"wl{i}"
                filter_parts.append(
                    f"[desktop]crop={w}:{h}:{x}:{y}[{label}]"
                )
                layer_labels.append((label, x, y))
            else:
                # Scale file input to target size
                fi = file_idx_map[i]
                label = f"fl{i}"
                filter_parts.append(
                    f"[{fi}:v]scale={w}:{h},format=yuv420p[{label}]"
                )
                layer_labels.append((label, x, y))
        
        # Overlay layers onto canvas sequentially
        current = "[0:v]"  # base canvas
        for idx, (label, ox, oy) in enumerate(layer_labels):
            out_label = f"[ov{idx}]"
            filter_parts.append(
                f"{current}[{label}]overlay={ox}:{oy}:shortest=1{out_label}"
            )
            current = out_label
        
        filter_str = "; ".join(filter_parts)
        
        cmd_str = (
            f'{" ".join(inputs)} '
            f'-filter_complex "{filter_str}" '
            f'-map "{current}" -map 1:a '
            f'-c:v libx264 -preset veryfast '
            f'-b:v {params.get("bitrate", "4500k")} '
            f'-maxrate {params.get("bitrate", "4500k")} '
            f'-bufsize {params.get("bufsize", "9000k")} '
            f'-pix_fmt yuv420p -g {params.get("gop", "60")} '
            f'-c:a aac -b:a 128k '
            f'-f flv "rtmp://a.rtmp.youtube.com/live2/{params["key"]}"'
        )
    else:
        try:
            cmd_str = preset_cfg["template"].format(**params)
        except KeyError as e:
            raise HTTPException(400, f"Missing parameter: {e}")

    session_id = f"ffmpeg_{uuid.uuid4().hex[:8]}"
    log_file = os.path.join(LIVESTREAM_DATA_DIR, f"{session_id}.log")
    os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)

    try:
        log_fh = open(log_file, "w", encoding="utf-8")
        proc = subprocess.Popen(
            f"ffmpeg {cmd_str}",
            shell=True,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
        )
        _ffmpeg_sessions[session_id] = {
            "process": proc,
            "pid": proc.pid,
            "broadcast_id": req.broadcast_id,
            "stream_key": req.stream_key[:8] + "...",
            "preset": req.preset,
            "input_source": req.input_source,
            "log_file": log_file,
            "log_fh": log_fh,
            "started_at": datetime.now().isoformat(),
            "status": "running",
        }
        # Update broadcast status
        if req.broadcast_id:
            data = _load_data()
            if req.broadcast_id in data.get("broadcasts", {}):
                data["broadcasts"][req.broadcast_id]["status"] = "streaming"
                data["broadcasts"][req.broadcast_id]["ffmpeg_session_id"] = session_id
                _save_data(data)

        threading.Thread(target=_monitor_ffmpeg, args=(session_id,), daemon=True).start()
        return {"status": "success", "session_id": session_id, "pid": proc.pid}
    except Exception as e:
        raise HTTPException(500, f"FFmpeg start failed: {str(e)}")


@router.post("/ffmpeg/stop/{session_id}")
async def api_stop_ffmpeg(session_id: str):
    if session_id not in _ffmpeg_sessions:
        raise HTTPException(404, f"Session '{session_id}' not found")
    _stop_ffmpeg_session(session_id)
    return {"status": "success", "message": f"Session '{session_id}' stopped."}


@router.get("/ffmpeg/sessions")
async def api_list_ffmpeg_sessions():
    result = []
    for sid, sess in _ffmpeg_sessions.items():
        proc = sess.get("process")
        is_running = proc is not None and proc.poll() is None
        result.append({
            "session_id": sid,
            "pid": sess.get("pid"),
            "broadcast_id": sess.get("broadcast_id", ""),
            "preset": sess.get("preset", ""),
            "started_at": sess.get("started_at", ""),
            "stopped_at": sess.get("stopped_at", ""),
            "status": "running" if is_running else "stopped",
            "exit_code": sess.get("exit_code"),
        })
    return {"sessions": result}


@router.get("/ffmpeg/log/{session_id}")
async def api_get_ffmpeg_log(session_id: str, tail: int = 50):
    sess = _ffmpeg_sessions.get(session_id)
    if not sess:
        raise HTTPException(404, f"Session '{session_id}' not found")
    log_file = sess.get("log_file", "")
    if not os.path.exists(log_file):
        return {"log": ""}
    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return {"session_id": session_id, "log": "".join(lines[-tail:])}
    except Exception as e:
        raise HTTPException(500, str(e))


# ══════════════════════════════════════════════════════════════════════
# AUTO GO LIVE (One-click)
# ══════════════════════════════════════════════════════════════════════

@router.post("/auto-live")
async def api_auto_go_live(req: AutoLiveRequest):
    """One-click: Create broadcast + bind + start FFmpeg."""
    # Step 1: create broadcast
    create_req = CreateBroadcastRequest(
        token_id=req.token_id,
        title=req.title,
        description=req.description,
        privacy=req.privacy,
        resolution=req.resolution,
        frame_rate=req.frame_rate,
    )
    result = await api_create_broadcast(create_req)
    broadcast = result["broadcast"]

    # Step 2: start FFmpeg
    ffmpeg_req = StartFFmpegRequest(
        stream_key=broadcast["stream_key"],
        preset=req.preset,
        input_source=req.input_source,
        custom_args=req.ffmpeg_args,
        broadcast_id=broadcast["broadcast_id"],
    )
    try:
        ffmpeg_result = await api_start_ffmpeg(ffmpeg_req)
        return {
            "status": "success",
            "broadcast": broadcast,
            "ffmpeg_session_id": ffmpeg_result.get("session_id"),
            "message": f"🔴 LIVE! '{req.title}' is streaming.",
        }
    except HTTPException as e:
        return {
            "status": "partial",
            "broadcast": broadcast,
            "ffmpeg_error": e.detail,
            "message": f"Broadcast created but FFmpeg failed: {e.detail}",
        }


# ══════════════════════════════════════════════════════════════════════
# SCHEDULES
# ══════════════════════════════════════════════════════════════════════

@router.get("/schedules")
async def api_list_schedules():
    return {"schedules": _load_schedules()}


@router.post("/schedules")
async def api_add_schedule(req: AddScheduleRequest):
    schedules = _load_schedules()
    schedule = req.model_dump()
    schedule["id"] = f"sched_{uuid.uuid4().hex[:8]}"
    schedule["created_at"] = datetime.now().isoformat()
    schedule["status"] = "pending"
    schedules.append(schedule)
    _save_schedules(schedules)
    return {"status": "success", "schedule": schedule}


@router.delete("/schedules/{schedule_id}")
async def api_remove_schedule(schedule_id: str):
    schedules = [s for s in _load_schedules() if s.get("id") != schedule_id]
    _save_schedules(schedules)
    return {"status": "success"}


# ══════════════════════════════════════════════════════════════════════
# WINDOWS (For Advanced Scene)
# ══════════════════════════════════════════════════════════════════════

def _get_active_windows() -> List[str]:
    try:
        import ctypes
        EnumWindows = ctypes.windll.user32.EnumWindows
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
        GetWindowText = ctypes.windll.user32.GetWindowTextW
        GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
        IsWindowVisible = ctypes.windll.user32.IsWindowVisible

        titles = []
        def foreach_window(hwnd, lParam):
            if IsWindowVisible(hwnd):
                length = GetWindowTextLength(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    GetWindowText(hwnd, buff, length + 1)
                    if buff.value and len(buff.value.strip()) > 0:
                        titles.append(buff.value)
            return True

        EnumWindows(EnumWindowsProc(foreach_window), 0)
        ignore_list = ["Program Manager", "Settings", "Microsoft Store"]
        return sorted(list(set([t for t in titles if t not in ignore_list])))
    except Exception as e:
        logger.error(f"Failed to get active windows: {e}")
        return []

@router.get("/windows")
async def api_get_windows():
    windows = _get_active_windows()
    return {"status": "success", "windows": windows}


# ══════════════════════════════════════════════════════════════════════
# UTILITIES
# ══════════════════════════════════════════════════════════════════════

@router.get("/ffmpeg-check")
async def api_check_ffmpeg():
    path = shutil.which("ffmpeg")
    if not path:
        return {"available": False, "path": None, "version": None}
    try:
        r = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
        version = r.stdout.split("\n")[0] if r.stdout else "unknown"
        return {"available": True, "path": path, "version": version}
    except Exception:
        return {"available": True, "path": path, "version": "unknown"}


@router.get("/presets")
async def api_get_presets():
    return {
        "presets": {
            k: {"label": v["label"], "description": v["description"], "defaults": v["defaults"]}
            for k, v in FFMPEG_PRESETS.items()
        }
    }
