"""
Livestream Extension — YouTube Livestream Manager with FFmpeg RTMP push.
Manages broadcasts, stream keys, and FFmpeg processes for multi-stream support.
"""
import os
import uuid
import json
import logging
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

try:
    from tubecli.core.extension_manager import Extension
    from tubecli.config import DATA_DIR
except ImportError:
    from zhiying.core.extension_manager import Extension
    DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "data")

logger = logging.getLogger("LivestreamExtension")

LIVESTREAM_DATA_DIR = os.path.join(str(DATA_DIR), "livestream")
LIVESTREAM_DATA_FILE = os.path.join(LIVESTREAM_DATA_DIR, "livestream_data.json")
SCHEDULES_FILE = os.path.join(LIVESTREAM_DATA_DIR, "schedules.json")

# YouTube Live Streaming API Base
YT_API_BASE = "https://www.googleapis.com/youtube/v3"

# FFmpeg presets
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
        "label": "🖥️ Screen → RTMP (Windows)",
        "description": "Stream desktop screen capture",
        "template": '-f gdigrab -framerate {fps} -i desktop -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 -c:v libx264 -preset ultrafast -b:v {bitrate} -maxrate {bitrate} -bufsize {bufsize} -pix_fmt yuv420p -g {gop} -c:a aac -b:a 128k -shortest -f flv "rtmp://a.rtmp.youtube.com/live2/{key}"',
        "defaults": {"bitrate": "3000k", "bufsize": "6000k", "gop": "60", "fps": "30"},
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
}


class LivestreamManager:
    """Manages YouTube livestreams and FFmpeg processes."""

    def __init__(self):
        self._data: Dict[str, Any] = {"broadcasts": {}, "sessions": {}}
        self._ffmpeg_processes: Dict[str, dict] = {}  # session_id -> {process, thread, ...}
        self._load()

    # ── Load / Save ──────────────────────────────────────────

    def _load(self):
        os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
        if os.path.exists(LIVESTREAM_DATA_FILE):
            try:
                with open(LIVESTREAM_DATA_FILE, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except Exception:
                self._data = {"broadcasts": {}, "sessions": {}}
        else:
            self._save()

    def _save(self):
        os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
        with open(LIVESTREAM_DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    # ── Auth Helper ──────────────────────────────────────────

    def _get_auth_manager(self):
        """Get auth_manager singleton from the auth_manager extension."""
        try:
            from tubecli.extensions.auth_manager.extension import auth_manager
            return auth_manager
        except ImportError:
            try:
                from zhiying.extensions.auth_manager.extension import auth_manager
                return auth_manager
            except ImportError:
                logger.error("auth_manager extension not available")
                return None

    def _get_token(self, token_id: str) -> Optional[str]:
        """Get active access token, auto-refreshing if needed."""
        am = self._get_auth_manager()
        if not am:
            return None
        return am.get_active_token(token_id)

    def _yt_headers(self, token: str) -> dict:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ── YouTube Credentials ──────────────────────────────────

    def list_youtube_credentials(self) -> List[dict]:
        """List auth credentials that have YouTube scope."""
        am = self._get_auth_manager()
        if not am:
            return []
        tokens = am.list_tokens(provider="google")
        yt_tokens = []
        for t in tokens:
            scopes = t.get("scopes", [])
            if any("youtube" in s for s in scopes):
                yt_tokens.append(t)
        return yt_tokens

    # ── Broadcasts (YouTube API) ─────────────────────────────

    def create_broadcast(
        self,
        token_id: str,
        title: str,
        description: str = "",
        privacy: str = "unlisted",
        scheduled_start: str = "",
        resolution: str = "1080p",
        frame_rate: str = "30fps",
    ) -> dict:
        """Create a YouTube broadcast + stream, bind them, return RTMP key."""
        import requests

        token = self._get_token(token_id)
        if not token:
            return {"status": "error", "message": "Failed to get access token. Re-authorize required."}

        headers = self._yt_headers(token)

        # Calculate scheduled start time
        if scheduled_start:
            start_time = scheduled_start
        else:
            start_time = (datetime.utcnow() + timedelta(seconds=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        # 1. Create liveBroadcast
        broadcast_body = {
            "snippet": {
                "title": title,
                "description": description,
                "scheduledStartTime": start_time,
            },
            "status": {
                "privacyStatus": privacy,
                "selfDeclaredMadeForKids": False,
            },
            "contentDetails": {
                "enableAutoStart": True,
                "enableAutoStop": True,
                "monitorStream": {"enableMonitorStream": False},
            },
        }

        try:
            resp = requests.post(
                f"{YT_API_BASE}/liveBroadcasts?part=snippet,status,contentDetails",
                headers=headers,
                json=broadcast_body,
                timeout=30,
            )
            if resp.status_code != 200:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                return {"status": "error", "message": f"Create broadcast failed: {error_msg}"}

            broadcast = resp.json()
            broadcast_id = broadcast["id"]
        except Exception as e:
            return {"status": "error", "message": f"Create broadcast error: {str(e)}"}

        # 2. Create liveStream
        stream_body = {
            "snippet": {
                "title": f"{title} - Stream",
            },
            "cdn": {
                "frameRate": frame_rate,
                "ingestionType": "rtmp",
                "resolution": resolution,
            },
        }

        try:
            resp = requests.post(
                f"{YT_API_BASE}/liveStreams?part=snippet,cdn",
                headers=headers,
                json=stream_body,
                timeout=30,
            )
            if resp.status_code != 200:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                return {"status": "error", "message": f"Create stream failed: {error_msg}"}

            stream = resp.json()
            stream_id = stream["id"]
            stream_key = stream["cdn"]["ingestionInfo"]["streamName"]
            ingestion_url = stream["cdn"]["ingestionInfo"]["ingestionAddress"]
        except Exception as e:
            return {"status": "error", "message": f"Create stream error: {str(e)}"}

        # 3. Bind broadcast to stream
        try:
            resp = requests.post(
                f"{YT_API_BASE}/liveBroadcasts/bind?id={broadcast_id}&part=id,contentDetails&streamId={stream_id}",
                headers=headers,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"Bind failed: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Bind error: {e}")

        # 4. Save to local data
        broadcast_data = {
            "broadcast_id": broadcast_id,
            "stream_id": stream_id,
            "title": title,
            "description": description,
            "privacy": privacy,
            "stream_key": stream_key,
            "ingestion_url": ingestion_url,
            "rtmp_url": f"{ingestion_url}/{stream_key}",
            "token_id": token_id,
            "resolution": resolution,
            "frame_rate": frame_rate,
            "status": "ready",
            "created_at": datetime.now().isoformat(),
            "scheduled_start": start_time,
        }
        self._data.setdefault("broadcasts", {})[broadcast_id] = broadcast_data
        self._save()

        return {
            "status": "success",
            "broadcast": broadcast_data,
            "message": f"Broadcast '{title}' created. Stream key: {stream_key}",
        }

    def list_broadcasts(self, token_id: str = "", include_youtube: bool = False) -> List[dict]:
        """List broadcasts (local data + optionally from YouTube API)."""
        self._load()
        local = list(self._data.get("broadcasts", {}).values())

        # Enrich with FFmpeg session info
        for b in local:
            bid = b.get("broadcast_id", "")
            for sid, sess in self._ffmpeg_processes.items():
                if sess.get("broadcast_id") == bid:
                    b["ffmpeg_session_id"] = sid
                    b["ffmpeg_running"] = sess.get("process") is not None and sess["process"].poll() is None
                    break

        if include_youtube and token_id:
            try:
                import requests
                token = self._get_token(token_id)
                if token:
                    resp = requests.get(
                        f"{YT_API_BASE}/liveBroadcasts?part=snippet,status&broadcastStatus=all&maxResults=25",
                        headers=self._yt_headers(token),
                        timeout=15,
                    )
                    if resp.status_code == 200:
                        items = resp.json().get("items", [])
                        return {"local": local, "youtube": items}
            except Exception as e:
                logger.warning(f"Failed to fetch YouTube broadcasts: {e}")

        return local

    def get_broadcast(self, broadcast_id: str) -> Optional[dict]:
        """Get a single broadcast by ID."""
        self._load()
        return self._data.get("broadcasts", {}).get(broadcast_id)

    def delete_broadcast(self, broadcast_id: str, token_id: str = "") -> dict:
        """Delete a broadcast (local + optionally from YouTube)."""
        self._load()

        # Stop FFmpeg if running
        for sid, sess in list(self._ffmpeg_processes.items()):
            if sess.get("broadcast_id") == broadcast_id:
                self.stop_ffmpeg(sid)

        # Delete from YouTube if token available
        if token_id:
            try:
                import requests
                token = self._get_token(token_id)
                if token:
                    requests.delete(
                        f"{YT_API_BASE}/liveBroadcasts?id={broadcast_id}",
                        headers=self._yt_headers(token),
                        timeout=15,
                    )
            except Exception:
                pass

        # Remove from local data
        if broadcast_id in self._data.get("broadcasts", {}):
            del self._data["broadcasts"][broadcast_id]
            self._save()

        return {"status": "success", "message": f"Broadcast '{broadcast_id}' deleted."}

    def transition_broadcast(self, token_id: str, broadcast_id: str, target_status: str) -> dict:
        """Transition broadcast status: testing → live → complete."""
        import requests

        token = self._get_token(token_id)
        if not token:
            return {"status": "error", "message": "No valid token."}

        try:
            resp = requests.post(
                f"{YT_API_BASE}/liveBroadcasts/transition?broadcastStatus={target_status}&id={broadcast_id}&part=status",
                headers=self._yt_headers(token),
                timeout=30,
            )
            if resp.status_code != 200:
                error_data = resp.json()
                error_msg = error_data.get("error", {}).get("message", resp.text[:200])
                return {"status": "error", "message": f"Transition failed: {error_msg}"}

            # Update local
            if broadcast_id in self._data.get("broadcasts", {}):
                self._data["broadcasts"][broadcast_id]["status"] = target_status
                self._save()

            return {"status": "success", "message": f"Broadcast transitioned to '{target_status}'."}
        except Exception as e:
            return {"status": "error", "message": f"Transition error: {str(e)}"}

    def get_stream_status(self, token_id: str, stream_id: str) -> dict:
        """Get the health/status of a YouTube stream."""
        import requests

        token = self._get_token(token_id)
        if not token:
            return {"status": "error", "message": "No valid token."}

        try:
            resp = requests.get(
                f"{YT_API_BASE}/liveStreams?part=status&id={stream_id}",
                headers=self._yt_headers(token),
                timeout=15,
            )
            if resp.status_code == 200:
                items = resp.json().get("items", [])
                if items:
                    status = items[0].get("status", {})
                    return {
                        "status": "success",
                        "stream_status": status.get("streamStatus", "unknown"),
                        "health_status": status.get("healthStatus", {}),
                    }
            return {"status": "error", "message": "Stream not found"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── FFmpeg Process Management ────────────────────────────

    def start_ffmpeg(
        self,
        stream_key: str,
        preset: str = "file",
        input_source: str = "",
        custom_args: dict = None,
        broadcast_id: str = "",
    ) -> dict:
        """Start an FFmpeg RTMP push process."""

        # Check FFmpeg availability
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            return {"status": "error", "message": "FFmpeg not found in PATH. Install FFmpeg first."}

        preset_config = FFMPEG_PRESETS.get(preset)
        if not preset_config:
            return {"status": "error", "message": f"Unknown preset: {preset}. Available: {list(FFMPEG_PRESETS.keys())}"}

        # Build command
        template = preset_config["template"]
        params = {**preset_config.get("defaults", {}), **(custom_args or {})}
        params["key"] = stream_key
        params["input"] = input_source

        try:
            cmd_str = template.format(**params)
        except KeyError as e:
            return {"status": "error", "message": f"Missing parameter: {e}. Required for preset '{preset}'."}

        full_cmd = f"ffmpeg {cmd_str}"
        session_id = f"ffmpeg_{uuid.uuid4().hex[:8]}"

        # Log file
        log_file = os.path.join(LIVESTREAM_DATA_DIR, f"{session_id}.log")

        try:
            log_fh = open(log_file, "w", encoding="utf-8")
            process = subprocess.Popen(
                full_cmd,
                shell=True,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
            )

            self._ffmpeg_processes[session_id] = {
                "process": process,
                "pid": process.pid,
                "broadcast_id": broadcast_id,
                "stream_key": stream_key[:8] + "...",
                "preset": preset,
                "input_source": input_source,
                "command": full_cmd[:200],
                "log_file": log_file,
                "log_fh": log_fh,
                "started_at": datetime.now().isoformat(),
                "status": "running",
            }

            # Update broadcast status
            if broadcast_id and broadcast_id in self._data.get("broadcasts", {}):
                self._data["broadcasts"][broadcast_id]["status"] = "streaming"
                self._data["broadcasts"][broadcast_id]["ffmpeg_session_id"] = session_id
                self._save()

            # Start monitor thread
            monitor = threading.Thread(target=self._monitor_ffmpeg, args=(session_id,), daemon=True)
            monitor.start()

            return {
                "status": "success",
                "session_id": session_id,
                "pid": process.pid,
                "message": f"FFmpeg started (PID {process.pid}). Streaming to YouTube...",
            }

        except Exception as e:
            return {"status": "error", "message": f"FFmpeg start error: {str(e)}"}

    def _monitor_ffmpeg(self, session_id: str):
        """Monitor FFmpeg process and update status on exit."""
        sess = self._ffmpeg_processes.get(session_id)
        if not sess or not sess.get("process"):
            return

        process = sess["process"]
        process.wait()  # Block until process exits

        sess["status"] = "stopped"
        sess["exit_code"] = process.returncode
        sess["stopped_at"] = datetime.now().isoformat()

        # Close log file handle
        try:
            if sess.get("log_fh"):
                sess["log_fh"].close()
        except Exception:
            pass

        # Update broadcast status
        bid = sess.get("broadcast_id", "")
        if bid and bid in self._data.get("broadcasts", {}):
            self._data["broadcasts"][bid]["status"] = "stopped"
            self._save()

        logger.info(f"FFmpeg session {session_id} stopped (exit code: {process.returncode})")

    def stop_ffmpeg(self, session_id: str) -> dict:
        """Stop an FFmpeg process."""
        sess = self._ffmpeg_processes.get(session_id)
        if not sess:
            return {"status": "error", "message": f"Session '{session_id}' not found."}

        process = sess.get("process")
        if process and process.poll() is None:
            try:
                # Send 'q' to FFmpeg for graceful stop
                process.stdin.write(b"q")
                process.stdin.flush()
                process.wait(timeout=5)
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=3)
                except Exception:
                    process.kill()

        sess["status"] = "stopped"
        sess["stopped_at"] = datetime.now().isoformat()

        # Close log file handle
        try:
            if sess.get("log_fh"):
                sess["log_fh"].close()
        except Exception:
            pass

        return {"status": "success", "message": f"FFmpeg session '{session_id}' stopped."}

    def list_ffmpeg_sessions(self) -> List[dict]:
        """List all FFmpeg sessions (active and stopped)."""
        result = []
        for sid, sess in self._ffmpeg_processes.items():
            is_running = sess.get("process") is not None and sess["process"].poll() is None
            result.append({
                "session_id": sid,
                "pid": sess.get("pid"),
                "broadcast_id": sess.get("broadcast_id", ""),
                "stream_key": sess.get("stream_key", ""),
                "preset": sess.get("preset", ""),
                "input_source": sess.get("input_source", ""),
                "started_at": sess.get("started_at", ""),
                "stopped_at": sess.get("stopped_at", ""),
                "status": "running" if is_running else "stopped",
                "exit_code": sess.get("exit_code"),
            })
        return result

    def get_ffmpeg_log(self, session_id: str, tail_lines: int = 50) -> dict:
        """Get recent log output from an FFmpeg session."""
        sess = self._ffmpeg_processes.get(session_id)
        if not sess:
            return {"status": "error", "message": f"Session '{session_id}' not found."}

        log_file = sess.get("log_file", "")
        if not os.path.exists(log_file):
            return {"status": "error", "message": "Log file not found."}

        try:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
                tail = lines[-tail_lines:] if len(lines) > tail_lines else lines
                return {
                    "status": "success",
                    "session_id": session_id,
                    "total_lines": len(lines),
                    "log": "".join(tail),
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── Auto Go Live (One-click) ─────────────────────────────

    def auto_go_live(
        self,
        token_id: str,
        title: str,
        description: str = "",
        privacy: str = "unlisted",
        input_source: str = "",
        preset: str = "file",
        ffmpeg_args: dict = None,
        resolution: str = "1080p",
        frame_rate: str = "30fps",
    ) -> dict:
        """One-click: create broadcast + stream + bind + start FFmpeg."""

        # 1. Create broadcast + stream
        result = self.create_broadcast(
            token_id=token_id,
            title=title,
            description=description,
            privacy=privacy,
            resolution=resolution,
            frame_rate=frame_rate,
        )
        if result["status"] != "success":
            return result

        broadcast = result["broadcast"]
        stream_key = broadcast["stream_key"]
        broadcast_id = broadcast["broadcast_id"]

        # 2. Start FFmpeg
        ffmpeg_result = self.start_ffmpeg(
            stream_key=stream_key,
            preset=preset,
            input_source=input_source,
            custom_args=ffmpeg_args,
            broadcast_id=broadcast_id,
        )

        if ffmpeg_result["status"] != "success":
            return {
                "status": "partial",
                "broadcast": broadcast,
                "ffmpeg_error": ffmpeg_result["message"],
                "message": f"Broadcast created but FFmpeg failed: {ffmpeg_result['message']}",
            }

        return {
            "status": "success",
            "broadcast": broadcast,
            "ffmpeg_session_id": ffmpeg_result["session_id"],
            "message": f"🔴 LIVE! '{title}' is streaming. FFmpeg PID: {ffmpeg_result['pid']}",
        }

    # ── Schedules ────────────────────────────────────────────

    def list_schedules(self) -> List[dict]:
        """List scheduled livestreams."""
        if not os.path.exists(SCHEDULES_FILE):
            return []
        try:
            with open(SCHEDULES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def add_schedule(self, schedule: dict) -> dict:
        """Add a scheduled livestream."""
        schedules = self.list_schedules()
        schedule["id"] = f"sched_{uuid.uuid4().hex[:8]}"
        schedule["created_at"] = datetime.now().isoformat()
        schedule["status"] = "pending"
        schedules.append(schedule)
        self._save_schedules(schedules)
        return {"status": "success", "schedule": schedule}

    def remove_schedule(self, schedule_id: str) -> dict:
        """Remove a scheduled livestream."""
        schedules = self.list_schedules()
        schedules = [s for s in schedules if s.get("id") != schedule_id]
        self._save_schedules(schedules)
        return {"status": "success", "message": f"Schedule '{schedule_id}' removed."}

    def _save_schedules(self, schedules: list):
        os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)
        with open(SCHEDULES_FILE, "w", encoding="utf-8") as f:
            json.dump(schedules, f, indent=2, ensure_ascii=False)

    def check_schedules(self):
        """Check and execute due scheduled livestreams. Called by scheduler."""
        schedules = self.list_schedules()
        now = datetime.now()
        updated = False

        for sched in schedules:
            if sched.get("status") != "pending":
                continue

            try:
                run_at = datetime.fromisoformat(sched["run_at"])
                if now >= run_at:
                    logger.info(f"Executing scheduled livestream: {sched.get('title', 'Untitled')}")
                    result = self.auto_go_live(
                        token_id=sched.get("token_id", ""),
                        title=sched.get("title", "Scheduled Stream"),
                        description=sched.get("description", ""),
                        privacy=sched.get("privacy", "unlisted"),
                        input_source=sched.get("input_source", ""),
                        preset=sched.get("preset", "file"),
                        ffmpeg_args=sched.get("ffmpeg_args"),
                        resolution=sched.get("resolution", "1080p"),
                        frame_rate=sched.get("frame_rate", "30fps"),
                    )
                    sched["status"] = "executed" if result.get("status") == "success" else "failed"
                    sched["result"] = result.get("message", "")
                    sched["executed_at"] = now.isoformat()
                    updated = True
            except Exception as e:
                sched["status"] = "failed"
                sched["result"] = str(e)
                updated = True

        if updated:
            self._save_schedules(schedules)

    # ── FFmpeg Check ─────────────────────────────────────────

    @staticmethod
    def check_ffmpeg() -> dict:
        """Check if FFmpeg is available."""
        path = shutil.which("ffmpeg")
        if not path:
            return {"available": False, "path": None, "version": None}
        try:
            r = subprocess.run([path, "-version"], capture_output=True, text=True, timeout=5)
            version_line = r.stdout.split("\n")[0] if r.stdout else ""
            return {"available": True, "path": path, "version": version_line}
        except Exception:
            return {"available": True, "path": path, "version": "unknown"}

    # ── Presets ──────────────────────────────────────────────

    @staticmethod
    def get_presets() -> dict:
        return {k: {"label": v["label"], "description": v["description"], "defaults": v["defaults"]}
                for k, v in FFMPEG_PRESETS.items()}


# Global singleton
livestream_manager = LivestreamManager()


class LivestreamExtension(Extension):
    name = "livestream"
    version = "1.0.0"
    description = "YouTube Livestream Manager — Create broadcasts, manage stream keys, and push RTMP with FFmpeg"
    author = "TubeCreate"

    def on_install(self):
        logger.info("Livestream Extension installed")
        os.makedirs(LIVESTREAM_DATA_DIR, exist_ok=True)

    def on_enable(self):
        logger.info("Livestream Extension enabled")
        ffmpeg_info = LivestreamManager.check_ffmpeg()
        if not ffmpeg_info["available"]:
            logger.warning("FFmpeg not found in PATH! Streaming will not work.")
        else:
            logger.info(f"FFmpeg: {ffmpeg_info['version']}")

    def get_routes(self):
        try:
            import livestream_api
            return livestream_api.router
        except Exception as e:
            logger.error(f"Failed to load livestream_api router: {e}")
            import traceback
            traceback.print_exc()
            return None
