# Fal AI Professional Video Description Web App

A Python application that uses Fal AI's video-understanding model to generate detailed descriptions of videos from URLs or local files.

## Features

- **Video Input Support**: Analyze videos from URLs or local files
- **Custom Prompts**: Use custom prompts to get specific information about videos
- **Error Handling**: Comprehensive error handling and validation
- **Command Line Interface**: Easy-to-use CLI with argparse
- **Multiple Video Formats**: Supports MP4, AVI, MOV, MKV, WebM, FLV

## Setup

```bash
pip install -r requirements.txt
export FAL_KEY="your-api-key-here"
```

Or add it to your shell profile (~/.bashrc, ~/.zshrc, etc.):

```bash
echo 'export FAL_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```

## Usage

### Command Line Interface

#### Analyze video from URL:

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8080
```

- UI: `http://localhost:8080/`
- AutoHDR Pipeline: `http://localhost:8080/autohdr`
- Templates: `http://localhost:8080/templates`
- History: `http://localhost:8080/history`
- Health: `http://localhost:8080/health`

## API Endpoints

- `POST /api/video/describe` (multipart/form-data: `video_url` or `file`, `prompt`)
- `POST /api/video/submit` (multipart/form-data: `video_url` or `file`, `prompt`, `webhook_url`)
- `GET /api/video/{request_id}/status`
- `GET /api/video/{request_id}/result`
- `POST /api/autohdr/runs` (multipart/form-data: `reference_video_url`, `photos`)
- `GET /api/autohdr/runs`
- `GET /api/autohdr/runs/{run_id}`
- `POST /api/autohdr/runs/{run_id}/compile`
- `POST /api/autohdr/runs/{run_id}/generate`
- `GET /api/templates`
- `POST /api/templates`
- `PUT /api/templates/{name}`
- `DELETE /api/templates/{name}`

## Docker

```bash
docker compose up --build video-description-web
```

Dev mode with hot reload:

```bash
docker compose up --build video-description-web-dev
```

## CLI Compatibility

The CLI remains available:

```bash
python video_description.py --url "https://example.com/video.mp4"
```

## Notes

- AutoHDR generation calls Fal image-edit and image-to-video endpoints, then stitches the generated clip URLs with `fal-ai/ffmpeg-api/compose`; no local preview renderer or local final-video assembly is included.
- Persistence is JSON-backed via `data/prompt_templates.json` and `data/processing_history.json`.
