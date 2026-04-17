#!/usr/bin/env python3
"""
Safe media downloader for media URLs you have permission to download.

Features:
- Lists available resolutions for HLS (.m3u8) master playlists
- Lists available formats for YouTube URLs via yt-dlp
- Downloads chosen video stream to MP4 when possible
- Converts downloaded media to MP3 using ffmpeg
- Works with direct .mp4 URLs, HLS playlists, and YouTube URLs

Requirements:
- Python 3.10+
- ffmpeg installed and available in PATH
- requests
- yt-dlp for YouTube support

Install:
    pip install requests yt-dlp

Examples:
    python safe_media_downloader.py info "https://example.com/video.m3u8"
    python safe_media_downloader.py download "https://example.com/video.m3u8" --resolution 1280x720 --output myvideo.mp4
    python safe_media_downloader.py download "https://example.com/file.mp4" --output clip.mp4
    python safe_media_downloader.py info "https://www.youtube.com/watch?v=VIDEO_ID"
    python safe_media_downloader.py download "https://www.youtube.com/watch?v=VIDEO_ID" --resolution 2160p --output myvideo.mp4
    python safe_media_downloader.py mp3 "https://example.com/file.mp4" --output audio.mp3

Notes:
- Use only with content you own or are allowed to download.
- Some HLS streams may be encrypted or protected; this tool does not bypass protection.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests

TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (compatible; SafeMediaDownloader/1.0)"
SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass
class HLSVariant:
    resolution: str
    bandwidth: Optional[int]
    url: str


def require_ffmpeg() -> None:
    if resolve_ffmpeg_command() is None:
        raise RuntimeError("ffmpeg is not installed or not in PATH.")


def require_ytdlp() -> None:
    if shutil.which("yt-dlp") is None:
        result = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("yt-dlp is not installed or not available to this Python interpreter.")


def resolve_ffmpeg_command() -> Optional[str]:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg is not None:
        return system_ffmpeg

    bundled_patterns = [
        SCRIPT_DIR / "ffmpeg" / "bin" / "ffmpeg.exe",
        SCRIPT_DIR / "ffmpeg" / "ffmpeg.exe",
        SCRIPT_DIR / "ffmpeg.exe",
    ]
    for candidate in bundled_patterns:
        if candidate.exists():
            return str(candidate)
    return None


def resolve_ffmpeg_location() -> Optional[str]:
    ffmpeg_cmd = resolve_ffmpeg_command()
    if ffmpeg_cmd is None:
        return None
    return str(Path(ffmpeg_cmd).resolve().parent)


def resolve_js_runtime() -> Optional[str]:
    deno_cmd = shutil.which("deno")
    if deno_cmd is not None:
        return f"deno:{deno_cmd}"

    node_cmd = shutil.which("node")
    if node_cmd is not None:
        return f"node:{node_cmd}"

    return None


def http_get_text(url: str) -> str:
    r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.text


def is_m3u8_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".m3u8")


def is_mp4_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(".mp4")


def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "youtu.be",
        "www.youtu.be",
    }


def parse_hls_master(master_url: str) -> List[HLSVariant]:
    text = http_get_text(master_url)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    variants: List[HLSVariant] = []
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = line.split(":", 1)[1]
            res_match = re.search(r"RESOLUTION=(\d+x\d+)", attrs)
            bw_match = re.search(r"BANDWIDTH=(\d+)", attrs)
            resolution = res_match.group(1) if res_match else "unknown"
            bandwidth = int(bw_match.group(1)) if bw_match else None

            if i + 1 < len(lines) and not lines[i + 1].startswith("#"):
                variant_url = urljoin(master_url, lines[i + 1])
                variants.append(HLSVariant(resolution=resolution, bandwidth=bandwidth, url=variant_url))

    return variants


def choose_variant(variants: List[HLSVariant], resolution: Optional[str]) -> HLSVariant:
    if not variants:
        raise ValueError("No HLS variants found.")

    if resolution:
        for v in variants:
            if v.resolution == resolution:
                return v
        available = ", ".join(v.resolution for v in variants)
        raise ValueError(f"Requested resolution not found. Available: {available}")

    def sort_key(v: HLSVariant):
        try:
            w, h = map(int, v.resolution.split("x"))
            pixels = w * h
        except Exception:
            pixels = -1
        return (pixels, v.bandwidth or -1)

    return sorted(variants, key=sort_key)[-1]


def run_ffmpeg(args: List[str]) -> None:
    ffmpeg_cmd = resolve_ffmpeg_command()
    if ffmpeg_cmd is None:
        raise RuntimeError("ffmpeg is not installed or not in PATH.")
    cmd = [ffmpeg_cmd, "-y", *args]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ffmpeg failed")


def run_ytdlp(args: List[str], capture_output: bool = False) -> subprocess.CompletedProcess[str]:
    require_ytdlp()
    require_ffmpeg()
    ffmpeg_location = resolve_ffmpeg_location()
    js_runtime = resolve_js_runtime()
    if shutil.which("yt-dlp") is not None:
        cmd = ["yt-dlp"]
        if ffmpeg_location is not None:
            cmd.extend(["--ffmpeg-location", ffmpeg_location])
        if js_runtime is not None:
            cmd.extend(["--js-runtimes", js_runtime])
        cmd.extend(args)
    else:
        cmd = [sys.executable, "-m", "yt_dlp"]
        if ffmpeg_location is not None:
            cmd.extend(["--ffmpeg-location", ffmpeg_location])
        if js_runtime is not None:
            cmd.extend(["--js-runtimes", js_runtime])
        cmd.extend(args)
    result = subprocess.run(cmd, capture_output=capture_output, text=True)
    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()
        message = stderr_text or stdout_text or "yt-dlp failed"
        raise RuntimeError(message)
    return result


def normalize_youtube_resolution(resolution: Optional[str]) -> Optional[int]:
    if not resolution:
        return None

    match = re.fullmatch(r"(?:(\d{3,4})p?|(\d{3,4})x(\d{3,4}))", resolution.strip().lower())
    if not match:
        raise ValueError("For YouTube, --resolution must look like 2160, 2160p, or 3840x2160.")

    if match.group(1):
        return int(match.group(1))
    return int(match.group(3))


def get_youtube_metadata(url: str) -> dict:
    result = run_ytdlp(["-J", "--no-playlist", url], capture_output=True)
    return json.loads(result.stdout)


def print_youtube_info(url: str) -> None:
    data = get_youtube_metadata(url)
    title = data.get("title") or "Unknown title"
    print(f"Title: {title}")

    formats = data.get("formats") or []
    seen: set[str] = set()
    resolutions: List[tuple[int, str]] = []

    for fmt in formats:
        height = fmt.get("height")
        width = fmt.get("width")
        if not height or not width:
            continue
        label = f"{width}x{height} ({height}p)"
        if label in seen:
            continue
        seen.add(label)
        resolutions.append((height, label))

    if not resolutions:
        print("No video resolutions found.")
        return

    print("Available video resolutions:")
    for _, label in sorted(resolutions):
        print(f"- {label}")


def download_youtube_to_mp4(url: str, output: Path, resolution: Optional[str]) -> None:
    max_height = normalize_youtube_resolution(resolution)
    fmt = (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]"
        if max_height
        else "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    )
    run_ytdlp([
        "--no-playlist",
        "-f", fmt,
        "--merge-output-format", "mp4",
        "-o", str(output),
        url,
    ])


def download_youtube_to_mp3(url: str, output: Path) -> None:
    run_ytdlp([
        "--no-playlist",
        "-x",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "-o", str(output),
        url,
    ])


def download_hls_to_mp4(url: str, output: Path) -> None:
    require_ffmpeg()
    run_ffmpeg([
        "-i", url,
        "-c", "copy",
        str(output),
    ])


def download_file(url: str, output: Path) -> None:
    with requests.get(url, stream=True, timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}) as r:
        r.raise_for_status()
        with open(output, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)


def convert_to_mp3(input_file: Path, output_file: Path) -> None:
    require_ffmpeg()
    run_ffmpeg([
        "-i", str(input_file),
        "-vn",
        "-acodec", "libmp3lame",
        "-q:a", "2",
        str(output_file),
    ])


def print_hls_info(url: str) -> None:
    variants = parse_hls_master(url)
    if not variants:
        print("No variants found. This may be a media playlist rather than a master playlist.")
        return

    print("Available resolutions:")
    for v in variants:
        bw = f", bandwidth={v.bandwidth}" if v.bandwidth else ""
        print(f"- {v.resolution}{bw}")


def cmd_info(args: argparse.Namespace) -> int:
    url = args.url
    if is_m3u8_url(url):
        print_hls_info(url)
    elif is_mp4_url(url):
        print("Direct MP4 URL detected. Single downloadable source.")
    elif is_youtube_url(url):
        print_youtube_info(url)
    else:
        print("Unknown URL type. Supported URLs: YouTube, direct .mp4, and .m3u8")
        return 1
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    url = args.url
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    if is_m3u8_url(url):
        variants = parse_hls_master(url)
        if variants:
            chosen = choose_variant(variants, args.resolution)
            print(f"Downloading HLS variant: {chosen.resolution}")
            download_hls_to_mp4(chosen.url, output)
        else:
            print("No master variants found; treating URL as media playlist.")
            download_hls_to_mp4(url, output)
    elif is_mp4_url(url):
        print("Downloading MP4 file...")
        download_file(url, output)
    elif is_youtube_url(url):
        print("Downloading YouTube video...")
        download_youtube_to_mp4(url, output, args.resolution)
    else:
        print("Unsupported URL. Supported URLs: YouTube, direct .mp4, and .m3u8")
        return 1

    print(f"Saved to: {output}")
    return 0


def cmd_mp3(args: argparse.Namespace) -> int:
    url = args.url
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_video = Path(tmpdir) / "temp_input.mp4"

        if is_m3u8_url(url):
            variants = parse_hls_master(url)
            chosen_url = choose_variant(variants, args.resolution).url if variants else url
            print("Downloading source for MP3 extraction...")
            download_hls_to_mp4(chosen_url, temp_video)
        elif is_mp4_url(url):
            print("Downloading source for MP3 extraction...")
            download_file(url, temp_video)
        elif is_youtube_url(url):
            print("Downloading YouTube audio as MP3...")
            download_youtube_to_mp3(url, output)
            print(f"Saved to: {output}")
            return 0
        else:
            print("Unsupported URL. Supported URLs: YouTube, direct .mp4, and .m3u8")
            return 1

        print("Converting to MP3...")
        convert_to_mp3(temp_video, output)

    print(f"Saved to: {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe media downloader for direct media URLs.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_info = sub.add_parser("info", help="List available resolutions or show source info")
    p_info.add_argument("url", help="YouTube URL or direct .m3u8/.mp4 URL")
    p_info.set_defaults(func=cmd_info)

    p_download = sub.add_parser("download", help="Download media to MP4")
    p_download.add_argument("url", help="YouTube URL or direct .m3u8/.mp4 URL")
    p_download.add_argument("--resolution", help="For HLS use 1280x720; for YouTube use 2160, 2160p, or 3840x2160")
    p_download.add_argument("--output", required=True, help="Output MP4 filename")
    p_download.set_defaults(func=cmd_download)

    p_mp3 = sub.add_parser("mp3", help="Download media and extract MP3")
    p_mp3.add_argument("url", help="YouTube URL or direct .m3u8/.mp4 URL")
    p_mp3.add_argument("--resolution", help="For HLS use 1280x720; ignored for YouTube MP3 output")
    p_mp3.add_argument("--output", required=True, help="Output MP3 filename")
    p_mp3.set_defaults(func=cmd_mp3)

    return parser


def main() -> int:
    try:
        parser = build_parser()
        args = parser.parse_args()
        return int(args.func(args))
    except requests.HTTPError as e:
        print(f"HTTP error: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
