from __future__ import annotations

import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
ASSETS_DIR = ROOT / "assets"
JOB_DIR = ROOT / ".clip_jobs"
VENDOR_DIR = ROOT / ".vendor"
MAX_SEGMENT_SECONDS = 900
ALLOWED_QUALITIES = (360, 480, 720, 1080)
GIF_MAX_WIDTH = 640
GIF_FPS = 10
GIF_MAX_COLORS = 256
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

if VENDOR_DIR.exists():
    sys.path.insert(0, str(VENDOR_DIR))


@dataclass
class Job:
    id: str
    status: str = "queued"
    progress: int = 0
    message: str = "En cola"
    filename: str | None = None
    path: Path | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


jobs: dict[str, Job] = {}
jobs_lock = threading.Lock()


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def require_yt_dlp():
    try:
        import yt_dlp  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Falta yt-dlp. Instala dependencias con: python3 -m pip install -r requirements.txt"
        ) from exc
    return yt_dlp


def validate_url(url: str) -> None:
    parsed = urlparse(url.strip())
    host = parsed.netloc.lower().removeprefix("www.")
    path_parts = [part for part in parsed.path.split("/") if part]
    video_id = ""
    if host == "youtu.be" and path_parts:
        video_id = path_parts[0]
    elif host in {"youtube.com", "m.youtube.com"}:
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(path_parts) >= 2 and path_parts[0] in {"shorts", "embed"}:
            video_id = path_parts[1]
    if parsed.scheme not in {"http", "https"} or not VIDEO_ID_RE.match(video_id):
        raise ValueError("Por favor, ingresa un enlace de YouTube válido.")


def seconds_to_hhmmss(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def available_qualities(formats: list[dict]) -> list[int]:
    found: set[int] = set()
    for fmt in formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec")
        if isinstance(height, int) and height in ALLOWED_QUALITIES and vcodec != "none":
            found.add(height)
    return sorted(found, reverse=True)


def get_metadata(url: str) -> dict:
    validate_url(url)
    yt_dlp = require_yt_dlp()
    options = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:  # yt-dlp exposes several extractor/download exceptions.
        raise RuntimeError("El video no está disponible (privado, eliminado o restringido).") from exc

    duration = int(info.get("duration") or 0)
    qualities = available_qualities(info.get("formats") or [])
    if not qualities:
        raise RuntimeError("No hay resoluciones compatibles disponibles para este video.")

    return {
        "id": info.get("id"),
        "title": info.get("title") or "Video de YouTube",
        "duration": duration,
        "durationLabel": seconds_to_hhmmss(duration),
        "thumbnail": info.get("thumbnail"),
        "qualities": qualities,
    }


def update_job(job_id: str, **changes) -> None:
    with jobs_lock:
        job = jobs.get(job_id)
        if job:
            for key, value in changes.items():
                setattr(job, key, value)


def timestamp_filename() -> str:
    return datetime.now().strftime("%Y-%m-%d_%Hh-%M-%S")


def parse_download_percent(line: str) -> int | None:
    match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
    if not match:
        return None
    percent = float(match.group(1))
    return min(80, max(5, int(percent * 0.8)))


def run_command(command: list[str], job_id: str, phase: str, progress_base: int = 0) -> None:
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                part
                for part in [str(VENDOR_DIR), os.environ.get("PYTHONPATH", "")]
                if part
            ),
        },
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    last_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        clean = line.strip()
        if clean:
            last_lines = (last_lines + [clean])[-8:]
            percent = parse_download_percent(clean)
            if percent is not None:
                update_job(job_id, progress=percent, message="Descargando fragmento")
            elif phase == "convert":
                update_job(job_id, progress=max(progress_base, 90), message="Codificando GIF")
    code = process.wait()
    if code != 0:
        detail = "\n".join(last_lines) or f"Comando falló con código {code}."
        raise RuntimeError(detail)


def build_format_selector(quality: int, include_audio: bool = True) -> str:
    if include_audio:
        return f"bestvideo[height={quality}]+bestaudio/best[height={quality}]"
    return f"bestvideo[height={quality}][acodec=none]/best[height={quality}][acodec=none]"


def build_downloader_args(include_audio: bool = True) -> str:
    audio_args = "-c:a aac -b:a 128k" if include_audio else "-an"
    return f"ffmpeg:-c:v libx264 -crf 28 -preset fast {audio_args}"


def parse_bool(value, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "si", "sí"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return default


def build_gif_filter(quality: int) -> str:
    return (
        f"fps={GIF_FPS},scale={GIF_MAX_WIDTH}:-2:flags=lanczos,"
        "split[s0][s1];"
        f"[s0]palettegen=max_colors={GIF_MAX_COLORS}:stats_mode=diff[p];"
        "[s1][p]paletteuse=dither=bayer:bayer_scale=2:diff_mode=rectangle"
    )


def parse_exclusions(raw_exclusions, start: int, end: int) -> list[tuple[int, int]]:
    if raw_exclusions is None:
        return []
    if not isinstance(raw_exclusions, list):
        raise ValueError("Los intervalos excluidos no tienen un formato válido.")

    exclusions: list[tuple[int, int]] = []
    for item in raw_exclusions:
        if not isinstance(item, dict):
            raise ValueError("Los intervalos excluidos no tienen un formato válido.")
        try:
            exclude_start = int(item.get("start", 0))
            exclude_end = int(item.get("end", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError("Los intervalos excluidos no tienen un formato válido.") from exc
        if exclude_start < start or exclude_end > end or exclude_end <= exclude_start:
            raise ValueError("Cada intervalo excluido debe estar dentro del rango principal.")
        exclusions.append((exclude_start, exclude_end))

    exclusions.sort()
    merged: list[tuple[int, int]] = []
    for exclude_start, exclude_end in exclusions:
        if merged and exclude_start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], exclude_end))
        else:
            merged.append((exclude_start, exclude_end))
    return merged


def kept_segments(start: int, end: int, exclusions: list[tuple[int, int]]) -> list[tuple[int, int]]:
    cursor = start
    segments: list[tuple[int, int]] = []
    for exclude_start, exclude_end in exclusions:
        if cursor < exclude_start:
            segments.append((cursor - start, exclude_start - start))
        cursor = max(cursor, exclude_end)
    if cursor < end:
        segments.append((cursor - start, end - start))
    return segments


def concat_file_line(path: Path) -> str:
    escaped = str(path.resolve()).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def remove_excluded_segments(source_path: Path, output_path: Path, segments: list[tuple[int, int]], job_id: str) -> None:
    segment_paths: list[Path] = []
    concat_path = JOB_DIR / f"{job_id}-concat.txt"
    try:
        for index, (segment_start, segment_end) in enumerate(segments):
            segment_path = JOB_DIR / f"{job_id}-keep-{index:02d}.mp4"
            segment_paths.append(segment_path)
            cut_command = [
                "ffmpeg",
                "-y",
                "-ss",
                str(segment_start),
                "-i",
                str(source_path),
                "-t",
                str(segment_end - segment_start),
                "-map",
                "0:v:0",
                "-map",
                "0:a:0?",
                "-c:v",
                "libx264",
                "-crf",
                "28",
                "-preset",
                "fast",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                str(segment_path),
            ]
            run_command(cut_command, job_id, "trim", progress_base=82)

        concat_path.write_text("".join(concat_file_line(path) for path in segment_paths), encoding="utf-8")
        concat_command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_path),
            "-c",
            "copy",
            str(output_path),
        ]
        run_command(concat_command, job_id, "trim", progress_base=84)
    finally:
        for path in segment_paths:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            concat_path.unlink()
        except OSError:
            pass


def process_job(job_id: str, payload: dict) -> None:
    try:
        url = str(payload.get("url", "")).strip()
        start = int(payload.get("start", 0))
        end = int(payload.get("end", 0))
        quality = int(payload.get("quality", 0))
        output_format = str(payload.get("format", "mp4")).lower()
        include_audio = parse_bool(payload.get("includeAudio", True)) if output_format == "mp4" else True

        if output_format not in {"mp4", "gif"}:
            raise ValueError("Formato no soportado.")
        if start < 0 or end <= start:
            raise ValueError("El tiempo de inicio debe ser menor que el tiempo de fin.")
        if end - start > MAX_SEGMENT_SECONDS:
            raise ValueError("El segmento solicitado excede el límite permitido por el servidor.")

        update_job(job_id, status="running", progress=2, message="Validando video")
        metadata = get_metadata(url)
        duration = int(metadata["duration"])
        if end > duration:
            end = duration
        if end <= start:
            raise ValueError("El rango queda fuera de la duración del video.")
        if quality not in metadata["qualities"]:
            raise ValueError("La resolución seleccionada no está disponible para este video.")
        exclusions = parse_exclusions(payload.get("exclusions", []), start, end)
        segments = kept_segments(start, end, exclusions)
        if not segments:
            raise ValueError("Los intervalos excluidos cubren todo el fragmento.")

        JOB_DIR.mkdir(exist_ok=True)
        raw_path = JOB_DIR / f"{job_id}-raw.%(ext)s"
        base_output = JOB_DIR / timestamp_filename()
        mp4_path = base_output.with_suffix(".mp4")

        update_job(job_id, progress=5, message="Descargando fragmento")
        download_command = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-playlist",
            "--newline",
            "--download-sections",
            f"*{seconds_to_hhmmss(start)}-{seconds_to_hhmmss(end)}",
            "-f",
            build_format_selector(quality, include_audio),
            "--merge-output-format",
            "mp4",
            "--downloader-args",
            build_downloader_args(include_audio),
            "-o",
            str(raw_path),
            url,
        ]
        run_command(download_command, job_id, "download")

        downloaded = sorted(JOB_DIR.glob(f"{job_id}-raw.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not downloaded:
            raise RuntimeError("No se generó el archivo de video.")
        downloaded_path = downloaded[0]
        if downloaded_path != mp4_path:
            shutil.move(str(downloaded_path), str(mp4_path))

        if exclusions:
            filtered_path = JOB_DIR / f"{job_id}-filtered.mp4"
            update_job(job_id, progress=82, message="Quitando intervalos excluidos")
            remove_excluded_segments(mp4_path, filtered_path, segments, job_id)
            try:
                mp4_path.unlink()
            except OSError:
                pass
            shutil.move(str(filtered_path), str(mp4_path))

        if output_format == "gif":
            gif_path = base_output.with_suffix(".gif")
            update_job(job_id, progress=85, message="Codificando GIF")
            gif_command = [
                "ffmpeg",
                "-y",
                "-i",
                str(mp4_path),
                "-filter_complex",
                build_gif_filter(quality),
                "-loop",
                "0",
                str(gif_path),
            ]
            run_command(gif_command, job_id, "convert", progress_base=85)
            try:
                mp4_path.unlink()
            except OSError:
                pass
            final_path = gif_path
        else:
            final_path = mp4_path

        update_job(
            job_id,
            status="done",
            progress=100,
            message="Listo para descargar",
            filename=final_path.name,
            path=final_path,
        )
    except Exception as exc:
        update_job(job_id, status="error", progress=0, message="Error", error=str(exc))


class ClipHandler(BaseHTTPRequestHandler):
    server_version = "ClipYouTube/1.0"

    def log_message(self, fmt: str, *args) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html")
        elif path.startswith("/static/"):
            self.serve_file(STATIC_DIR / path.removeprefix("/static/"))
        elif path.startswith("/assets/"):
            self.serve_file(ASSETS_DIR / path.removeprefix("/assets/"))
        elif path.startswith("/api/jobs/"):
            self.handle_job_status(path.rsplit("/", 1)[-1])
        elif path.startswith("/downloads/"):
            self.handle_download(path.rsplit("/", 1)[-1])
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/":
            self.serve_file(STATIC_DIR / "index.html", include_body=False)
        elif path.startswith("/static/"):
            self.serve_file(STATIC_DIR / path.removeprefix("/static/"), include_body=False)
        elif path.startswith("/assets/"):
            self.serve_file(ASSETS_DIR / path.removeprefix("/assets/"), include_body=False)
        elif path.startswith("/downloads/"):
            self.handle_download(path.rsplit("/", 1)[-1], include_body=False)
        else:
            self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/metadata":
                data = read_json(self)
                json_response(self, 200, {"ok": True, "video": get_metadata(str(data.get("url", "")))})
            elif parsed.path == "/api/extract":
                data = read_json(self)
                job_id = uuid.uuid4().hex
                with jobs_lock:
                    jobs[job_id] = Job(id=job_id)
                thread = threading.Thread(target=process_job, args=(job_id, data), daemon=True)
                thread.start()
                json_response(self, 202, {"ok": True, "jobId": job_id})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            json_response(self, 400, {"ok": False, "error": str(exc)})
        except RuntimeError as exc:
            json_response(self, 503, {"ok": False, "error": str(exc)})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": f"Error inesperado: {exc}"})

    def serve_file(self, path: Path, include_body: bool = True) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def handle_job_status(self, job_id: str) -> None:
        with jobs_lock:
            job = jobs.get(job_id)
            if not job:
                json_response(self, 404, {"ok": False, "error": "Trabajo no encontrado."})
                return
            payload = {
                "ok": True,
                "id": job.id,
                "status": job.status,
                "progress": job.progress,
                "message": job.message,
                "error": job.error,
                "downloadUrl": f"/downloads/{job.id}" if job.status == "done" else None,
                "filename": job.filename,
            }
        json_response(self, 200, payload)

    def handle_download(self, job_id: str, include_body: bool = True) -> None:
        with jobs_lock:
            job = jobs.get(job_id)
            path = job.path if job else None
            filename = job.filename if job else None
        if not path or not filename or not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("PORT", "13200"))
    server = ThreadingHTTPServer(("127.0.0.1", port), ClipHandler)
    print(f"Extractor listo en http://127.0.0.1:{port}")
    print("Ctrl+C para detener.")
    server.serve_forever()


if __name__ == "__main__":
    main()
