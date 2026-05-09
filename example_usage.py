#!/usr/bin/env python3
"""
Example usage of the Video Description Agent

This script demonstrates how to use the VideoDescriptionAgent class
to get AI-generated descriptions for videos.
"""

import os
from video_description import VideoDescriptionAgent


def example_url_usage():
    """Example of analyzing a video from URL."""
    print("=== Example: Video Description from URL ===")
    
    # Initialize the agent
    agent = VideoDescriptionAgent()
    
    # Example video URL (replace with actual video URL)
    video_url = "https://example.com/sample-video.mp4"
    
    try:
        # Get video description with custom prompt
        result = agent.describe_video_from_url(
            video_url, 
            "What is happening in this video? Describe the main activities and objects."
        )
        
        # Print the description
        agent.print_description(result)
        
    except Exception as e:
        print(f"Error: {e}")


def example_file_usage():
    """Example of analyzing a local video file."""
    print("\n=== Example: Video Description from Local File ===")
    
    # Initialize the agent
    agent = VideoDescriptionAgent()
    
    # Example local video file (replace with actual file path)
    video_path = "path/to/your/video.mp4"
    
    try:
        # Get video description with default prompt
        result = agent.describe_video_from_file(video_path)
        
        # Print the description
        agent.print_description(result)
        
    except Exception as e:
        print(f"Error: {e}")


def example_custom_prompts():
    """Example of using different custom prompts."""
    print("\n=== Example: Custom Prompts ===")
    
    agent = VideoDescriptionAgent()
    
    prompts = [
        "Describe the setting and environment in this video.",
        "What are the main objects or people visible in this video?",
        "Summarize the key events happening in this video.",
        "What emotions or mood does this video convey?",
        "Describe any technical aspects like camera work or editing."
    ]
    
    video_url = "https://example.com/sample-video.mp4"
    
    for i, prompt in enumerate(prompts, 1):
        print(f"\n--- Prompt {i}: {prompt} ---")
        try:
            result = agent.describe_video_from_url(video_url, prompt)
            if "data" in result and "description" in result["data"]:
                print(result["data"]["description"][:200] + "..." if len(result["data"]["description"]) > 200 else result["data"]["description"])
        except Exception as e:
            print(f"Error: {e}")


def main():
    """Run all examples."""
    print("Video Description Agent - Example Usage")
    print("=" * 50)
    
    # Check if API key is set
    if not os.getenv("FAL_KEY"):
        print("Error: FAL_KEY environment variable not set.")
        print("Please set your Fal AI API key:")
        print("export FAL_KEY='your-api-key-here'")
        return
    
    # Run examples (commented out since they require actual video URLs/files)
    print("Note: These examples use placeholder video URLs/paths.")
    print("Replace them with actual video URLs or file paths to test.")
    
    # Uncomment to run examples:
    # example_url_usage()
    # example_file_usage()
    # example_custom_prompts()
    
    print("\nTo test with actual videos:")
    print("1. Replace the placeholder URLs/file paths in the examples")
    print("2. Uncomment the function calls")
    print("3. Run this script again")


if __name__ == "__main__":
    main()
