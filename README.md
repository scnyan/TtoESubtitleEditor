# TtoE Subtitle Editor

Time to Explain subtitle editor for Brawl Stars video subtitles.

## Features

- Browse and search subtitle rows by time, speaker, topic, and text.
- Edit original/Japanese subtitles, speaker, topic, and display time.
- Preview subtitles over the source video.
- Customize subtitle position, width, scale, colors, outline, shadow, and pop animation.
- Export separate Japanese and English subtitle-only MP4 assets locally.
- Use shorts-friendly subtitle splits without breaking words or stacking multiple speaker blocks.

## Run Locally

```powershell
python -m pip install -r requirements.txt
python web_server.py
```

Open:

```text
http://127.0.0.1:8787
```

## GitHub Pages

The root `index.html` can be published directly with GitHub Pages. Static Pages mode can browse and preview subtitle data, while local Flask mode is still required for saving edits and exporting MP4 assets.

## Notes

Large video files are not intended for GitHub commits. Place the local preview video in the project folder as `video_preview.mp4` or `video.webm`.
