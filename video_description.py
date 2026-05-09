#!/usr/bin/env python3
"""CLI wrapper for the Fal AI Video Description service."""

import argparse
import sys

from src.app.core.config import get_settings
from src.app.services.fal_service import FalVideoService


class VideoDescriptionAgent:
    def __init__(self):
        self.service = FalVideoService(get_settings())

    def describe_video_from_url(self, video_url: str, prompt: str = "Describe this video in detail.") -> dict:
        return self.service.describe_video_from_url(video_url, prompt)

    def submit_video_from_url(self, video_url: str, prompt: str, webhook_url: str | None = None):
        return self.service.submit_video_from_url(video_url, prompt, webhook_url)

    def describe_video_from_file(self, video_path: str, prompt: str = "Describe this video in detail.") -> dict:
        return self.service.describe_video_from_file(video_path, prompt)

    def submit_video_from_file(self, video_path: str, prompt: str, webhook_url: str | None = None):
        return self.service.submit_video_from_file(video_path, prompt, webhook_url)

    def get_request_status(self, request_id: str):
        return self.service.get_request_status(request_id)

    def get_request_result(self, request_id: str):
        return self.service.get_request_result(request_id)

    def print_description(self, result: dict):
        if "data" in result and "description" in result["data"]:
            print("\n" + "=" * 50)
            print("VIDEO DESCRIPTION")
            print("=" * 50)
            print(result["data"]["description"])
            print("=" * 50)
        else:
            print("\nUnexpected response format:")
            print(result)


def main():
    parser = argparse.ArgumentParser(description="Get AI-generated descriptions for videos using Fal AI")
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--url", help="URL of the video to analyze")
    input_group.add_argument("--file", help="Path to local video file")
    input_group.add_argument("--request-id", help="Existing Fal request ID to check queue status")
    input_group.add_argument("--result-id", help="Existing Fal request ID to fetch final result payload")
    parser.add_argument("--prompt", default="Describe this video in detail.")
    parser.add_argument("--webhook-url", default=None)
    parser.add_argument("--async-submit", action="store_true")
    args = parser.parse_args()

    try:
        agent = VideoDescriptionAgent()

        if args.request_id:
            print(agent.get_request_status(args.request_id))
            return
        if args.result_id:
            agent.print_description(agent.get_request_result(args.result_id))
            return

        if args.async_submit:
            handle = (
                agent.submit_video_from_url(args.url, args.prompt, args.webhook_url)
                if args.url
                else agent.submit_video_from_file(args.file, args.prompt, args.webhook_url)
            )
            print(f"request_id: {getattr(handle, 'request_id', None)}")
            print(f"status_url: {getattr(handle, 'status_url', None)}")
            print(f"response_url: {getattr(handle, 'response_url', None)}")
            return

        result = (
            agent.describe_video_from_url(args.url, args.prompt)
            if args.url
            else agent.describe_video_from_file(args.file, args.prompt)
        )
        agent.print_description(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
