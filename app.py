import os
import re
import tempfile
import shutil
import uuid
import logging

from flask import Flask, request, jsonify, Response, stream_with_context, send_file
from flask_cors import CORS
import yt_dlp
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("allvideodl")

app = Flask(__name__)
CORS(app)  # allow calls from your website + Android app

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
MAX_FILESIZE_BYTES = 500 * 1024 * 1024  # 500MB safety cap for free-tier bandwidth
TMP_DIR = os.path.join(tempfile.gettempdir(), "allvideodl")
os.makedirs(TMP_DIR, exist_ok=True)

COMMON_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    # Helps a bit with basic bot-detection on some sites. Not a fix for
    # YouTube's stricter checks — see notes in README.
    "http_headers": {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    },
}


def safe_filename(name: str) -> str:
    name = re.sub(r"[^\w\-. ]", "_", name).strip()
    return name[:120] if name else "video"


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/api/info", methods=["POST"])
def info():
    """
    Body: { "url": "<video link>" }
    Returns: title, thumbnail, duration, and a list of downloadable formats
    (video qualities + an audio-only option) that the client can show,
    mirroring the quality-picker UI in the app.
    """
    data = request.get_json(silent=True) or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing 'url'"}), 400

    ydl_opts = {**COMMON_YDL_OPTS, "skip_download": True}

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        logger.warning("extract_info failed for %s: %s", url, e)
        return jsonify({"error": "Could not read this link.", "detail": str(e)}), 422

    if "entries" in result:  # playlist safety, take first entry only
        result = result["entries"][0]

    formats = []
    seen_heights = set()
    for f in result.get("formats", []):
        height = f.get("height")
        vcodec = f.get("vcodec")
        acodec = f.get("acodec")
        ext = f.get("ext")

        # Only offer progressive (video+audio) or video-only mp4 streams
        if vcodec == "none":
            continue
        if height is None:
            continue
        if height in seen_heights:
            continue

        seen_heights.add(height)
        formats.append({
            "format_id": f.get("format_id"),
            "label": f"{height}p",
            "ext": ext,
            "has_audio": acodec != "none",
            "filesize_approx": f.get("filesize") or f.get("filesize_approx"),
        })

    formats.sort(key=lambda x: int(x["label"].rstrip("p")), reverse=True)

    # Always offer an audio-only option
    formats.append({
        "format_id": "bestaudio",
        "label": "Audio Only",
        "ext": "mp3",
        "has_audio": True,
        "filesize_approx": None,
    })

    return jsonify({
        "title": result.get("title"),
        "thumbnail": result.get("thumbnail"),
        "duration": result.get("duration"),
        "source": result.get("extractor_key"),
        "formats": formats,
    })


@app.route("/api/download", methods=["GET"])
def download():
    """
    Query params: url=<video link>&format_id=<id from /api/info>
    Streams the file back to the client. Audio-only requests are converted
    to mp3 server-side (requires ffmpeg to be installed in the environment).
    """
    url = request.args.get("url", "").strip()
    format_id = request.args.get("format_id", "").strip()
    if not url or not format_id:
        return jsonify({"error": "Missing 'url' or 'format_id'"}), 400

    job_id = uuid.uuid4().hex
    job_dir = os.path.join(TMP_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    is_audio = format_id == "bestaudio"

    ydl_opts = {
        **COMMON_YDL_OPTS,
        "outtmpl": os.path.join(job_dir, "%(title)s.%(ext)s"),
    }

    if is_audio:
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]
    else:
        # progressive-or-merge: video format + best audio, muxed to mp4
        ydl_opts["format"] = f"{format_id}+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.extract_info(url, download=True)
    except yt_dlp.utils.DownloadError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        logger.warning("download failed for %s (%s): %s", url, format_id, e)
        return jsonify({"error": "Download failed.", "detail": str(e)}), 422

    files = os.listdir(job_dir)
    if not files:
        shutil.rmtree(job_dir, ignore_errors=True)
        return jsonify({"error": "No output file produced."}), 500

    filepath = os.path.join(job_dir, files[0])
    download_name = safe_filename(files[0])

    def cleanup_and_stream():
        try:
            with open(filepath, "rb") as f:
                while chunk := f.read(1024 * 1024):
                    yield chunk
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)

    return Response(
        stream_with_context(cleanup_and_stream()),
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
