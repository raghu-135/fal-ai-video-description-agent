# Fal AI Video Description Agent

A Python application that uses Fal AI's video-understanding model to generate detailed descriptions of videos from URLs or local files.

## Features

- **Video Input Support**: Analyze videos from URLs or local files
- **Custom Prompts**: Use custom prompts to get specific information about videos
- **Error Handling**: Comprehensive error handling and validation
- **Command Line Interface**: Easy-to-use CLI with argparse
- **Multiple Video Formats**: Supports MP4, AVI, MOV, MKV, WebM, FLV

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Up API Key

Get your API key from [Fal AI](https://fal.ai/) and set it as an environment variable:

```bash
export FAL_KEY="your-api-key-here"
```

Or add it to your shell profile (~/.bashrc, ~/.zshrc, etc.):

```bash
echo 'export FAL_KEY="your-api-key-here"' >> ~/.bashrc
source ~/.bashrc
```

## Docker Usage (Recommended)

### 1. Create `.env`

Copy the example file and set your values:

```bash
cp .env.example .env
```

`.env` should contain:

```env
FAL_KEY=your-fal-api-key-here
VIDEO_URL=https://example.com/video.mp4
WEBHOOK_URL=https://your-server.com/api/fal/webhook
```

`WEBHOOK_URL` is optional. Only pass it when you have a valid public HTTPS endpoint.

### 2. Build the container

```bash
docker compose build video-description
```

### 3. Submit async queue request

```bash
docker compose run --rm video-description
```

This submits the video job and returns:
- `request_id`
- `status_url`
- `response_url`

### 4. Check request status

```bash
docker compose run --rm video-description --request-id <request_id>
```

### 5. Fetch completed result

Once status is `Completed`, fetch the response payload:

```bash
curl -H "Authorization: Key $FAL_KEY" \
  "https://queue.fal.run/fal-ai/video-understanding/requests/<request_id>"
```

### Optional: submit with webhook

```bash
docker compose run --rm video-description --webhook-url "https://your-public-webhook-url"
```

## Local Python Usage

### Command Line Interface

#### Analyze video from URL (blocking):

```bash
python video_description.py --url "https://example.com/video.mp4"
```

#### Analyze local video file (blocking):

```bash
python video_description.py --file "/path/to/your/video.mp4"
```

#### Use custom prompt:

```bash
python video_description.py --url "https://example.com/video.mp4" --prompt "What objects are visible in this video?"
```

#### Help:

```bash
python video_description.py --help
```

#### Submit async queue request:

```bash
python video_description.py --url "https://example.com/video.mp4" --async-submit
```

#### Submit async queue request with webhook:

```bash
python video_description.py --url "https://example.com/video.mp4" --async-submit --webhook-url "https://your-public-webhook-url"
```

#### Check queue status:

```bash
python video_description.py --request-id "<request_id>"
```

### Programmatic Usage

```python
from video_description import VideoDescriptionAgent

# Initialize the agent
agent = VideoDescriptionAgent()

# Analyze video from URL
result = agent.describe_video_from_url(
    "https://example.com/video.mp4",
    "Describe this video in detail."
)
agent.print_description(result)

# Analyze local video file
result = agent.describe_video_from_file("path/to/video.mp4")
agent.print_description(result)
```

## Examples

Check out `example_usage.py` for more detailed examples of how to use the VideoDescriptionAgent class.

## Supported Video Formats

- MP4 (.mp4)
- AVI (.avi)
- MOV (.mov)
- MKV (.mkv)
- WebM (.webm)
- FLV (.flv)

## API Reference

The app uses the `fal-ai/video-understanding` model. For more details about the model and its capabilities, visit:
- [Model Documentation](https://fal.ai/models/fal-ai/video-understanding)
- [API Reference](https://fal.ai/models/fal-ai/video-understanding/api)

## Error Handling

The app includes comprehensive error handling for:
- Missing API keys
- Invalid video formats
- Network issues
- File not found errors
- API rate limits

## Requirements

- Python 3.11+ (for local `str | None` type syntax used in this project)
- Fal AI API key
- Internet connection for API calls

## License

This project is provided as-is for educational and development purposes.
