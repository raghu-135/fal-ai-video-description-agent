# Fal AI Video Description Agent

A Python application that uses Fal AI's video-understanding model and a local AutoHDR style-transfer scaffold for real estate photo-to-video experiments.

## Features

- **Video Input Support**: Analyze videos from URLs or local files
- **Custom Prompts**: Use custom prompts to get specific information about videos
- **Error Handling**: Comprehensive error handling and validation
- **Command Line Interface**: Easy-to-use CLI with argparse
- **Multiple Video Formats**: Supports MP4, AVI, MOV, MKV, WebM, FLV
- **AutoHDR Style Pipeline**: Maps a destination photoshoot onto the reference MP4 style and emits a render plan with selected assets, variant requests, prompts, and quality gates.

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

## Usage

### AutoHDR Local Style Pipeline

From this folder:

```bash
python -m autohdr_pipeline.pipeline
```

Default inputs:

- `../SnapInsta-Ai_3827468812233464997.mp4`
- `../video-hackathon-public/216_Anmer_Hall_Fort_Wayne_IN_46845`

Default outputs:

- `examples/anmer_reference_mapping/reference_style_template.local.json`
- `examples/anmer_reference_mapping/photo_inventory.local.json`
- `examples/anmer_reference_mapping/render_plan.local.json`

The render plan treats destination photos as processable ingredients. Each shot includes a local asset selection, top candidate trace, optional image-edit request, video prompt, negative prompt, and a `multimodalCompilerRequest` payload for a stronger image-aware compiler to override the local heuristic.

To render a local preview MP4 from the selected photos:

```bash
python -m autohdr_pipeline.pipeline --preview
```

This creates `examples/anmer_reference_mapping/preview.mp4`. It is an animatic: it approximates the planned camera moves with pan/zoom on the selected stills and attaches reference audio when available.

To also run the Fal full-video span prompt:

```bash
python -m autohdr_pipeline.pipeline --fal-span-graph
```

The pipeline reads `FAL_KEY` from the environment or from a local `.env` file.

To use Fal's OpenRouter video endpoint with Gemini 3.1 Pro Preview and compile the render plan from the extracted AI style:

```bash
python -m autohdr_pipeline.pipeline \
  --ai-style \
  --video-understanding-endpoint openrouter/router/video \
  --video-understanding-model google/gemini-3.1-pro-preview \
  --reference-url "https://r2-public.waqaas.workers.dev/SnapInsta-Ai_3827468812233464997.mp4" \
  --preview \
  --preview-output examples/anmer_reference_mapping/preview_ai_gemini31.mp4 \
  --preview-width 960 \
  --preview-height 540 \
  --preview-fps 12 \
  --preview-debug-labels
```

This writes `reference_style_template.ai.json`, `render_plan.ai.json`, `fal_span_graph.*.json`, and `preview_ai_gemini31.mp4`.

### Command Line Interface

#### Analyze video from URL:

```bash
python video_description.py --url "https://example.com/video.mp4"
```

#### Analyze local video file:

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

- Python 3.7+
- Fal AI API key
- Internet connection for API calls

## License

This project is provided as-is for educational and development purposes.
