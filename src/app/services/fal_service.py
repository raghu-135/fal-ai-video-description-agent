from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import fal_client

from src.app.core.config import Settings

VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"}
logger = logging.getLogger(__name__)


class FalVideoService:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model = settings.fal_model
        self.describe_model = settings.fal_describe_model
        self.describe_app = settings.fal_describe_app

    def _resolve_describe_target(self, model_choice: str) -> tuple[str, dict[str, Any]]:
        choice = (model_choice or "default").strip().lower()
        if choice == "gemini_pro":
            return self.describe_app, {"model": self.describe_model, "reasoning": True}
        if choice == "default":
            return self.model, {}
        raise ValueError("model_choice must be either 'default' or 'gemini_pro'")

    @staticmethod
    def _normalize_temperature(temperature: float | None) -> float | None:
        if temperature is None:
            return None
        value = float(temperature)
        if value < 0.0 or value > 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return value

    def validate_video_file(self, video_path: str) -> None:
        path = Path(video_path)
        if not path.exists():
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if path.suffix.lower() not in VIDEO_EXTENSIONS:
            allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
            raise ValueError(
                f"Unsupported video format: {path.suffix.lower()}. Supported formats: {allowed}"
            )

    def describe_video_from_url(
        self,
        video_url: str,
        prompt: str,
        temperature: float | None = None,
        model_choice: str = "default",
    ) -> dict[str, Any]:
        try:
            choice = (model_choice or "default").strip().lower()
            app_id, model_args = self._resolve_describe_target(choice)
            arguments: dict[str, Any] = {"video_url": video_url, "prompt": prompt, **model_args}
            normalized_temperature = self._normalize_temperature(temperature)
            if normalized_temperature is not None and choice == "gemini_pro":
                arguments["temperature"] = normalized_temperature
            result = fal_client.subscribe(
                app_id,
                arguments=arguments,
            )
            logger.info("Fal describe_video_from_url response: %s", result)
            return result
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error processing video: {exc}") from exc

    def submit_video_from_url(self, video_url: str, prompt: str, webhook_url: str | None = None):
        try:
            return fal_client.submit(
                self.model,
                arguments={"video_url": video_url, "prompt": prompt},
                webhook_url=webhook_url,
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error submitting video request: {exc}") from exc

    def describe_video_from_file(
        self,
        video_path: str,
        prompt: str,
        temperature: float | None = None,
        model_choice: str = "default",
    ) -> dict[str, Any]:
        self.validate_video_file(video_path)
        try:
            uploaded_video_url = fal_client.upload_file(video_path)
            choice = (model_choice or "default").strip().lower()
            app_id, model_args = self._resolve_describe_target(choice)
            arguments: dict[str, Any] = {"video_url": uploaded_video_url, "prompt": prompt, **model_args}
            normalized_temperature = self._normalize_temperature(temperature)
            if normalized_temperature is not None and choice == "gemini_pro":
                arguments["temperature"] = normalized_temperature
            result = fal_client.subscribe(
                app_id,
                arguments=arguments,
            )
            logger.info("Fal describe_video_from_file response: %s", result)
            return result
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error processing video file: {exc}") from exc

    def submit_video_from_file(self, video_path: str, prompt: str, webhook_url: str | None = None):
        self.validate_video_file(video_path)
        try:
            uploaded_video_url = fal_client.upload_file(video_path)
            return fal_client.submit(
                self.model,
                arguments={"video_url": uploaded_video_url, "prompt": prompt},
                webhook_url=webhook_url,
            )
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error submitting video file request: {exc}") from exc

    def get_request_status(self, request_id: str):
        try:
            status = fal_client.status(self.model, request_id, with_logs=True)
            logger.info("Fal get_request_status response for %s: %s", request_id, status)
            return status
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error checking request status: {exc}") from exc

    def get_request_result(self, request_id: str):
        try:
            result = fal_client.result(self.model, request_id)
            logger.info("Fal get_request_result response for %s: %s", request_id, result)
            return result
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(f"Error fetching request result: {exc}") from exc
