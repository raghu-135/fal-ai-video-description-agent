#!/usr/bin/env python3
"""
Video Description Agent using Fal AI

This script allows you to upload a video and get AI-generated descriptions
using the fal-ai/video-understanding model.
"""

import os
import sys
import argparse
from pathlib import Path
import fal_client


class VideoDescriptionAgent:
    def __init__(self):
        """Initialize the video description agent."""
        # Check for API key
        self.api_key = os.getenv("FAL_KEY")
        if not self.api_key:
            raise ValueError(
                "FAL_KEY environment variable not set. "
                "Please set your Fal AI API key: export FAL_KEY='your-api-key-here'"
            )
        
        # fal-client reads FAL_KEY from environment.
    
    def describe_video_from_url(self, video_url: str, prompt: str = "Describe this video in detail.") -> dict:
        """
        Get video description from a video URL.
        
        Args:
            video_url: URL of the video to analyze
            prompt: Custom prompt for the AI (optional)
            
        Returns:
            Dictionary containing the video description results
        """
        try:
            result = fal_client.subscribe(
                "fal-ai/video-understanding",
                arguments={
                    "video_url": video_url,
                    "prompt": prompt
                }
            )
            return result
        except Exception as e:
            raise RuntimeError(f"Error processing video: {str(e)}")

    def submit_video_from_url(self, video_url: str, prompt: str, webhook_url: str | None = None):
        """Submit an async queue request for a video URL."""
        try:
            return fal_client.submit(
                "fal-ai/video-understanding",
                arguments={
                    "video_url": video_url,
                    "prompt": prompt
                },
                webhook_url=webhook_url
            )
        except Exception as e:
            raise RuntimeError(f"Error submitting video request: {str(e)}")
    
    def describe_video_from_file(self, video_path: str, prompt: str = "Describe this video in detail.") -> dict:
        """
        Upload a local video file and get description.
        
        Args:
            video_path: Path to local video file
            prompt: Custom prompt for the AI (optional)
            
        Returns:
            Dictionary containing the video description results
        """
        # Validate file exists
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")
        
        # Check file extension
        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']
        file_ext = Path(video_path).suffix.lower()
        if file_ext not in video_extensions:
            raise ValueError(f"Unsupported video format: {file_ext}. Supported formats: {', '.join(video_extensions)}")
        
        try:
            # Upload local file, then pass returned URL to the model
            uploaded_video_url = fal_client.upload_file(video_path)
            result = fal_client.subscribe(
                "fal-ai/video-understanding",
                arguments={
                    "video_url": uploaded_video_url,
                    "prompt": prompt
                }
            )
            return result
        except Exception as e:
            raise RuntimeError(f"Error processing video file: {str(e)}")

    def submit_video_from_file(self, video_path: str, prompt: str, webhook_url: str | None = None):
        """Upload local file and submit async queue request."""
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        video_extensions = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']
        file_ext = Path(video_path).suffix.lower()
        if file_ext not in video_extensions:
            raise ValueError(f"Unsupported video format: {file_ext}. Supported formats: {', '.join(video_extensions)}")

        try:
            uploaded_video_url = fal_client.upload_file(video_path)
            return fal_client.submit(
                "fal-ai/video-understanding",
                arguments={
                    "video_url": uploaded_video_url,
                    "prompt": prompt
                },
                webhook_url=webhook_url
            )
        except Exception as e:
            raise RuntimeError(f"Error submitting video file request: {str(e)}")

    def get_request_status(self, request_id: str):
        """Get queue status for an existing request id."""
        try:
            return fal_client.status("fal-ai/video-understanding", request_id, with_logs=True)
        except Exception as e:
            raise RuntimeError(f"Error checking request status: {str(e)}")

    def get_request_result(self, request_id: str):
        """Get final queue result payload for an existing request id."""
        try:
            return fal_client.result("fal-ai/video-understanding", request_id)
        except Exception as e:
            raise RuntimeError(f"Error fetching request result: {str(e)}")
    
    def print_description(self, result: dict):
        """Print the video description in a formatted way."""
        if "data" in result and "description" in result["data"]:
            print("\n" + "="*50)
            print("VIDEO DESCRIPTION")
            print("="*50)
            print(result["data"]["description"])
            print("="*50)
        else:
            print("\nUnexpected response format:")
            print(result)


def main():
    """Main function to handle command line arguments."""
    parser = argparse.ArgumentParser(
        description="Get AI-generated descriptions for videos using Fal AI"
    )
    
    # Input options (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--url", 
        help="URL of the video to analyze"
    )
    input_group.add_argument(
        "--file", 
        help="Path to local video file"
    )
    input_group.add_argument(
        "--request-id",
        help="Existing Fal request ID to check queue status"
    )
    input_group.add_argument(
        "--result-id",
        help="Existing Fal request ID to fetch final result payload"
    )
    
    # Optional arguments
    parser.add_argument(
        "--prompt", 
        default="Describe this video in detail.",
        help="Custom prompt for the AI (default: 'Describe this video in detail.')"
    )
    parser.add_argument(
        "--webhook-url",
        default=None,
        help="Webhook URL for async queue completion callback"
    )
    parser.add_argument(
        "--async-submit",
        action="store_true",
        help="Submit to Fal queue and return request metadata immediately"
    )
    
    args = parser.parse_args()
    
    try:
        # Initialize the agent
        agent = VideoDescriptionAgent()
        
        # Request status check mode
        if args.request_id:
            status = agent.get_request_status(args.request_id)
            print(status)
            return

        # Request result mode
        if args.result_id:
            result = agent.get_request_result(args.result_id)
            agent.print_description(result)
            return

        # Async submit mode
        if args.async_submit:
            if args.url:
                print(f"Submitting video URL to queue: {args.url}")
                handle = agent.submit_video_from_url(args.url, args.prompt, args.webhook_url)
            else:
                print(f"Submitting video file to queue: {args.file}")
                handle = agent.submit_video_from_file(args.file, args.prompt, args.webhook_url)

            print("\n" + "=" * 50)
            print("REQUEST SUBMITTED")
            print("=" * 50)
            print(f"request_id: {handle.request_id}")
            if hasattr(handle, "status_url"):
                print(f"status_url: {handle.status_url}")
            if hasattr(handle, "response_url"):
                print(f"response_url: {handle.response_url}")
            print("=" * 50)
            return

        # Blocking mode
        if args.url:
            print(f"Analyzing video from URL: {args.url}")
            result = agent.describe_video_from_url(args.url, args.prompt)
        else:
            print(f"Analyzing video file: {args.file}")
            result = agent.describe_video_from_file(args.file, args.prompt)
        
        # Print results
        agent.print_description(result)
        
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
