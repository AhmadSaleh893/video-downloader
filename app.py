from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from flask import Flask, render_template, request, send_from_directory, url_for

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from safe_media_downloader import (  # noqa: E402
    choose_variant,
    download_file,
    download_hls_to_mp4,
    download_youtube_to_mp3,
    download_youtube_to_mp4,
    get_youtube_metadata,
    is_m3u8_url,
    is_mp4_url,
    is_youtube_url,
    parse_hls_master,
)

app = Flask(__name__)


def slugify_filename(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value or "download"


def pick_extension(kind: str) -> str:
    return ".mp3" if kind == "mp3" else ".mp4"


def summarize_url(url: str) -> dict[str, Any]:
    if is_youtube_url(url):
        metadata = get_youtube_metadata(url)
        formats = metadata.get("formats") or []
        resolutions: list[str] = []
        seen: set[str] = set()

        for item in formats:
            width = item.get("width")
            height = item.get("height")
            if not width or not height:
                continue
            label = f"{width}x{height} ({height}p)"
            if label in seen:
                continue
            seen.add(label)
            resolutions.append(label)

        resolutions.sort(key=lambda label: int(label.split("(")[-1].rstrip("p)")))
        return {
            "source_type": "YouTube",
            "title": metadata.get("title") or "Unknown title",
            "resolutions": resolutions,
        }

    if is_m3u8_url(url):
        variants = parse_hls_master(url)
        return {
            "source_type": "HLS playlist",
            "title": "Direct HLS stream",
            "resolutions": [variant.resolution for variant in variants],
        }

    if is_mp4_url(url):
        return {
            "source_type": "Direct MP4",
            "title": "Direct MP4 file",
            "resolutions": [],
        }

    raise ValueError("Unsupported URL. Use a YouTube, .m3u8, or .mp4 link.")


def perform_download(url: str, resolution: str | None, media_kind: str, filename_base: str) -> str:
    output_path = DOWNLOAD_DIR / f"{slugify_filename(filename_base)}{pick_extension(media_kind)}"

    if media_kind == "mp3":
        if is_youtube_url(url):
            download_youtube_to_mp3(url, output_path)
            return output_path.name
        raise ValueError("MP3 output is currently supported for YouTube links only.")

    if is_youtube_url(url):
        download_youtube_to_mp4(url, output_path, resolution or None)
        return output_path.name

    if is_m3u8_url(url):
        variants = parse_hls_master(url)
        if variants:
            chosen = choose_variant(variants, resolution or None)
            download_hls_to_mp4(chosen.url, output_path)
        else:
            download_hls_to_mp4(url, output_path)
        return output_path.name

    if is_mp4_url(url):
        download_file(url, output_path)
        return output_path.name

    raise ValueError("Unsupported URL. Use a YouTube, .m3u8, or .mp4 link.")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/inspect")
def inspect_url():
    url = (request.form.get("url") or "").strip()
    info = None
    error = None

    try:
        if not url:
            raise ValueError("Please enter a video URL.")
        info = summarize_url(url)
    except Exception as exc:
        error = str(exc)

    return render_template("index.html", url=url, info=info, error=error)


@app.post("/download")
def download():
    url = (request.form.get("url") or "").strip()
    resolution = (request.form.get("resolution") or "").strip()
    media_kind = (request.form.get("media_kind") or "mp4").strip().lower()
    filename_base = (request.form.get("filename") or "video-download").strip()

    info = None
    error = None
    download_name = None
    download_href = None

    try:
        if not url:
            raise ValueError("Please enter a video URL.")
        info = summarize_url(url)
        download_name = perform_download(url, resolution, media_kind, filename_base)
        download_href = url_for("serve_download", filename=download_name)
    except Exception as exc:
        error = str(exc)

    return render_template(
        "index.html",
        url=url,
        info=info,
        error=error,
        selected_resolution=resolution,
        selected_kind=media_kind,
        filename_base=filename_base,
        download_name=download_name,
        download_href=download_href,
    )


@app.get("/downloads/<path:filename>")
def serve_download(filename: str):
    return send_from_directory(DOWNLOAD_DIR, filename, as_attachment=True)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
