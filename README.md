# Fal AI Professional Video Description Web App

A FastAPI + NiceGUI web application for generating AI-powered video descriptions using Fal AI's `fal-ai/video-understanding` model.

## Features

- Web UI dashboard for URL-based video analysis
- Prompt template CRUD management
- Processing history view
- REST APIs for describe/submit/status/result
- CLI compatibility preserved (`video_description.py`)
- Dockerized deployment

## Requirements

- Python 3.11+
- `FAL_KEY` environment variable

## Setup

```bash
pip install -r requirements.txt
export FAL_KEY="your-api-key-here"
```

## Run Web App Locally

```bash
uvicorn src.app.main:app --host 0.0.0.0 --port 8080
```

- UI: `http://localhost:8080/`
- Templates: `http://localhost:8080/templates`
- History: `http://localhost:8080/history`
- Health: `http://localhost:8080/health`

## API Endpoints

- `POST /api/video/describe` (multipart/form-data: `video_url` or `file`, `prompt`)
- `POST /api/video/submit` (multipart/form-data: `video_url` or `file`, `prompt`, `webhook_url`)
- `GET /api/video/{request_id}/status`
- `GET /api/video/{request_id}/result`
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

- Video preview in browsers works best for direct media URLs compatible with the HTML `<video>` element.
- Persistence is JSON-backed via `data/prompt_templates.json` and `data/processing_history.json`.
