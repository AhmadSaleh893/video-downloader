# Downloader Web App

This is a small website wrapper around `safe_media_downloader.py`.

## Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

Open:

`http://127.0.0.1:5000`

## What it does

- Inspect a YouTube, `.m3u8`, or `.mp4` URL
- Show detected resolutions
- Download MP4 output
- Download MP3 output for YouTube links

## Notes

- Downloads are saved into the `downloads/` folder locally.
- This app is a good fit for local use or a real Python host.
- Vercel is not a great fit for long-running video downloads because serverless functions are short-lived and local storage is temporary.
- If you still deploy to Vercel, use temporary storage under `/tmp` and return the file directly in the same request instead of relying on a persistent `downloads/` directory.
- For Vercel, bundle a Linux `ffmpeg` binary at `bin/ffmpeg` inside this repo so the downloader can find it at runtime.
