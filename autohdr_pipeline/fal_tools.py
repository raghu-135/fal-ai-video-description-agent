"""Fal model helpers for reference video understanding."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .prompts import FULL_VIDEO_SPAN_PROMPT, SEGMENT_STYLE_PROMPT


class FalVideoUnderstandingAgent:
    """Thin wrapper around fal-ai/video-understanding."""

    default_endpoint = "fal-ai/video-understanding"
    openrouter_endpoint = "openrouter/router/video"
    vision_endpoint = "openrouter/router/vision"

    def __init__(self) -> None:
        load_dotenv_if_needed()
        self.api_key = os.getenv("FAL_KEY")
        if not self.api_key:
            raise ValueError("FAL_KEY environment variable is not set.")

    def analyze_url(
        self,
        video_url: str,
        prompt: str,
        *,
        endpoint: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        detailed_analysis: bool = False,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        import fal_client

        endpoint = endpoint or self.default_endpoint
        if endpoint == self.openrouter_endpoint:
            arguments: dict[str, Any] = {
                "video_urls": [video_url],
                "prompt": prompt,
                "model": model or "google/gemini-3.1-pro-preview",
                "temperature": temperature,
                "reasoning": True,
            }
            if system_prompt:
                arguments["system_prompt"] = system_prompt
            if max_tokens:
                arguments["max_tokens"] = max_tokens
        else:
            arguments = {
                "video_url": video_url,
                "prompt": prompt,
                "detailed_analysis": detailed_analysis,
            }
        return fal_client.subscribe(
            endpoint,
            arguments=arguments,
        )

    def analyze_file(self, video_path: Path, prompt: str, **kwargs: Any) -> dict[str, Any]:
        import fal_client

        uploaded_url = fal_client.upload_file(str(video_path))
        return self.analyze_url(uploaded_url, prompt, **kwargs)

    def analyze_images(
        self,
        image_urls: list[str],
        prompt: str,
        *,
        model: str = "google/gemini-3.1-pro-preview",
        system_prompt: str | None = None,
        reasoning: bool = True,
        temperature: float = 0.1,
        max_tokens: int | None = 12000,
    ) -> dict[str, Any]:
        import fal_client

        arguments: dict[str, Any] = {
            "image_urls": image_urls,
            "prompt": prompt,
            "model": model,
            "reasoning": reasoning,
            "temperature": temperature,
        }
        if system_prompt:
            arguments["system_prompt"] = system_prompt
        if max_tokens:
            arguments["max_tokens"] = max_tokens
        return fal_client.subscribe(self.vision_endpoint, arguments=arguments)

    @staticmethod
    def output_text(result: dict[str, Any]) -> str:
        if isinstance(result.get("output"), str):
            return result["output"]
        data = result.get("data")
        if isinstance(data, dict) and isinstance(data.get("description"), str):
            return data["description"]
        return json.dumps(result)

    def span_graph_from_file(self, video_path: Path, **kwargs: Any) -> dict[str, Any]:
        return self.analyze_file(video_path, FULL_VIDEO_SPAN_PROMPT, **kwargs)

    def span_graph_from_url(self, video_url: str, **kwargs: Any) -> dict[str, Any]:
        return self.analyze_url(video_url, FULL_VIDEO_SPAN_PROMPT, **kwargs)

    @classmethod
    def parsed_output_json(cls, result: dict[str, Any]) -> dict[str, Any] | None:
        text = cls.output_text(result).strip()
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL)
        if fenced:
            text = fenced.group(1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def style_fragment_from_file(
        self,
        video_path: Path,
        span_id: str,
        span_type: str,
        span_start: float,
        span_end: float,
        parent_context_summary: str,
        full_video_style_summary: str,
    ) -> dict[str, Any]:
        prompt = (
            SEGMENT_STYLE_PROMPT.replace("{{span_id}}", span_id)
            .replace("{{span_type}}", span_type)
            .replace("{{span_start}}", str(span_start))
            .replace("{{span_end}}", str(span_end))
            .replace("{{parent_context_summary}}", parent_context_summary)
            .replace("{{full_video_style_summary}}", full_video_style_summary)
        )
        return self.analyze_file(video_path, prompt)


def load_dotenv_if_needed(path: Path = Path(".env")) -> None:
    if os.getenv("FAL_KEY") or not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key.strip() == "FAL_KEY":
            os.environ["FAL_KEY"] = value.strip().strip('"').strip("'")
            return
