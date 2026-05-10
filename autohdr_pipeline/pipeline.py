#!/usr/bin/env python3
"""CLI for the local AutoHDR style pipeline scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ai_style_template import build_ai_style_template
from .compiler import compile_render_plan
from .fal_tools import FalVideoUnderstandingAgent
from .generation import IMAGE_EDIT_ENDPOINT, VIDEO_ENDPOINT_QUALITY, generate_and_assemble
from .multimodal_compiler import run_multimodal_compile
from .photo_inventory import analyze_photoshoot
from .preview_renderer import render_preview
from .prompts import FULL_VIDEO_SPAN_PROMPT
from .segment_style_fragments import DEFAULT_FILENAME as SHOT_STYLE_FRAGMENTS_FILENAME
from .segment_style_fragments import extract_shot_style_fragments, load_shot_style_fragments
from .style_template import build_local_style_template
from .utils import probe_video, write_json


def build_local_plan(
    reference: Path,
    photoshoot: Path,
    output_dir: Path,
    style: dict[str, object] | None = None,
    style_filename: str = "reference_style_template.local.json",
    render_plan_filename: str = "render_plan.local.json",
) -> dict[str, object]:
    style = style or build_local_style_template(reference)
    inventory = analyze_photoshoot(photoshoot)
    render_plan = compile_render_plan(style, inventory)

    write_json(output_dir / style_filename, style)
    write_json(output_dir / "photo_inventory.local.json", inventory)
    write_json(output_dir / render_plan_filename, render_plan)
    return {"style": style, "inventory": inventory, "render_plan": render_plan}


def write_fal_span_graph(reference: Path, output_dir: Path, reference_url: str | None = None) -> None:
    agent = FalVideoUnderstandingAgent()
    result = agent.span_graph_from_url(reference_url) if reference_url else agent.span_graph_from_file(reference)
    write_json(output_dir / "fal_span_graph.raw.json", result)
    parsed = agent.parsed_output_json(result)
    if parsed is not None:
        write_json(output_dir / "fal_span_graph.parsed.json", parsed)
        write_json(output_dir / "fal_span_graph.validation.json", validate_span_graph(parsed, reference, reference_url))


def fetch_fal_span_graph(
    reference: Path,
    output_dir: Path,
    reference_url: str | None,
    endpoint: str,
    model: str | None,
    max_tokens: int | None,
    temperature: float,
) -> dict[str, object] | None:
    agent = FalVideoUnderstandingAgent()
    metadata = probe_video(reference)
    prompt = full_video_prompt_with_metadata(metadata)
    kwargs = {
        "endpoint": endpoint,
        "model": model,
        "system_prompt": "You are a precise real-estate video style parser. Return strict JSON only.",
        "max_tokens": max_tokens,
        "temperature": temperature,
        "detailed_analysis": True,
    }
    result = agent.analyze_url(reference_url, prompt, **kwargs) if reference_url else agent.analyze_file(reference, prompt, **kwargs)
    write_json(output_dir / "fal_span_graph.raw.json", result)
    parsed = agent.parsed_output_json(result)
    if parsed is not None:
        write_json(output_dir / "fal_span_graph.parsed.json", parsed)
        write_json(output_dir / "fal_span_graph.validation.json", validate_span_graph(parsed, reference, reference_url))
    return parsed


def full_video_prompt_with_metadata(metadata: dict[str, object]) -> str:
    duration = metadata.get("duration_seconds")
    cut_candidates = metadata.get("cut_candidates_seconds")
    intervals = candidate_intervals(duration, cut_candidates)
    return (
        FULL_VIDEO_SPAN_PROMPT
        + "\n\nDeterministic metadata from local analysis:\n"
        + f"- duration_seconds: {duration}\n"
        + f"- candidate_cut_timestamps_seconds: {cut_candidates}\n"
        + f"- candidate_shot_intervals_seconds: {json.dumps(intervals)}\n\n"
        + "Creative event extraction requirements:\n"
        + "- Do not reduce the video to a normal real-estate tour summary. The reference has unusual visual edits.\n"
        + "- Capture apparent weather/season changes, furniture/staging changes while staying in a room, whip/zoom/speed-ramp transitions, impossible angle bridges, match cuts, and music-synced state changes.\n"
        + "- You may add extra JSON fields when useful, especially creativeEvents on spans. Prefer rich natural-language payloads inside those objects over narrow enums.\n"
        + "- For each creativeEvents item, include kind, tags, description, referenceEvidence, timing, and executionHint.\n\n"
        + "Critical extraction requirements:\n"
        + "1. All timestamps must be within 0 and duration_seconds.\n"
        + "2. Output one granular shot span for every candidate_shot_intervals_seconds item. Do not collapse a montage or transition sequence into one broad shot.\n"
        + "3. The candidate_cut_timestamps_seconds list is the timeline source of truth. If two adjacent intervals show similar content, still output separate shot spans and explain the edit/motion difference.\n"
        + "4. A 96-second reference video is expected to have dozens of shot spans, not a 10-12 shot summary. If uncertain, prefer more granular low-confidence shot spans over merged spans.\n"
        + "5. Output music_phrase spans, transition spans, and micro_event spans whenever they influence a shot's generated behavior.\n"
        + "6. For each shot span, fill content.spaceType, content.shotScale, style.stylisticFunction, style.cameraMotion, style.transitionIn, style.transitionOut, style.energyLevel, transferability, and any creativeEvents.\n"
        + "7. Preserve broad property_section and music_phrase spans, but do not omit shot-level spans.\n"
    )


def candidate_intervals(duration: object, cut_candidates: object) -> list[dict[str, object]]:
    if not isinstance(duration, (int, float)) or not isinstance(cut_candidates, list):
        return []
    cuts = sorted({round(float(cut), 3) for cut in cut_candidates if isinstance(cut, (int, float)) and 0 < cut < float(duration)})
    boundaries = [0.0, *cuts, round(float(duration), 3)]
    return [
        {"id": f"candidate_shot_{index:03d}", "start": start, "end": end}
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), 1)
        if end - start >= 0.25
    ]


def validate_span_graph(parsed: dict[str, object], reference: Path, reference_url: str | None = None) -> dict[str, object]:
    metadata = probe_video(reference)
    deterministic_duration = metadata.get("duration_seconds")
    video_summary = parsed.get("video_summary", {})
    model_duration = video_summary.get("estimated_duration_seconds") if isinstance(video_summary, dict) else None
    span_graph = parsed.get("span_graph", [])
    out_of_range = []
    if isinstance(deterministic_duration, (int, float)) and isinstance(span_graph, list):
        for span in span_graph:
            if not isinstance(span, dict):
                continue
            time_range = span.get("timeRange")
            if not isinstance(time_range, dict):
                continue
            end = time_range.get("end")
            if isinstance(end, (int, float)) and end > deterministic_duration + 0.5:
                out_of_range.append(
                    {
                        "id": span.get("id"),
                        "type": span.get("type"),
                        "timeRange": time_range,
                    }
                )
    duration_ratio = None
    if isinstance(deterministic_duration, (int, float)) and isinstance(model_duration, (int, float)) and deterministic_duration:
        duration_ratio = round(model_duration / deterministic_duration, 3)
    return {
        "schema": "fal_span_graph_validation.v1",
        "referenceUrl": reference_url,
        "deterministicDurationSeconds": deterministic_duration,
        "modelEstimatedDurationSeconds": model_duration,
        "durationRatio": duration_ratio,
        "spanCount": len(span_graph) if isinstance(span_graph, list) else None,
        "outOfRangeSpanCount": len(out_of_range),
        "outOfRangeSpanSample": out_of_range[:10],
        "recommendations": [
            "Use deterministic ffprobe duration, cut candidates, and beat grid as the timeline source of truth.",
            "Treat Fal span timestamps as semantic hints until rescaled or corrected.",
            "Ask the style merger to clip or rescale model spans before compiling shot slots.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Map a photoshoot to the reference MP4 style.")
    parser.add_argument(
        "--reference",
        type=Path,
        default=Path("../SnapInsta-Ai_3827468812233464997.mp4"),
        help="Reference MP4 path.",
    )
    parser.add_argument(
        "--photoshoot",
        type=Path,
        default=Path("../video-hackathon-public/216_Anmer_Hall_Fort_Wayne_IN_46845"),
        help="Destination photoshoot folder.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("examples/anmer_reference_mapping"),
        help="Directory for generated JSON artifacts.",
    )
    parser.add_argument(
        "--render-plan-input",
        type=Path,
        help="Load an existing render plan JSON and skip style/photo compilation.",
    )
    parser.add_argument(
        "--fal-span-graph",
        action="store_true",
        help="Also call Fal video-understanding with the full-video span prompt.",
    )
    parser.add_argument(
        "--ai-style",
        action="store_true",
        help="Compile render plan from the AI-extracted span graph instead of the local blueprint.",
    )
    parser.add_argument(
        "--reuse-parsed-span-graph",
        action="store_true",
        help="Use output-dir/fal_span_graph.parsed.json instead of calling video understanding again.",
    )
    parser.add_argument(
        "--shot-style-fragments",
        action="store_true",
        help="Run the second segment style prompt for shot spans only and merge the fragments into the AI style template.",
    )
    parser.add_argument(
        "--reuse-shot-style-fragments",
        action="store_true",
        help=f"Use output-dir/{SHOT_STYLE_FRAGMENTS_FILENAME} instead of rerunning per-shot segment style extraction.",
    )
    parser.add_argument(
        "--shot-style-fragments-input",
        type=Path,
        help="Existing shot style fragments JSON to merge into the AI style template.",
    )
    parser.add_argument(
        "--shot-style-fragments-max-shots",
        type=int,
        default=None,
        help="Optional cap for testing the second prompt on only the first N shot spans.",
    )
    parser.add_argument(
        "--shot-style-fragments-max-tokens",
        type=int,
        default=16000,
        help="Max tokens for each per-shot segment style extraction call.",
    )
    parser.add_argument(
        "--shot-style-fragments-parallelism",
        type=int,
        default=1,
        help="Number of per-shot segment style extraction calls to run in parallel. Use 0 for all shot spans.",
    )
    parser.add_argument(
        "--ai-style-max-shots",
        type=int,
        default=None,
        help="Optional cap for compiled AI shot slots. Defaults to all granular shot spans.",
    )
    parser.add_argument(
        "--video-understanding-endpoint",
        default="fal-ai/video-understanding",
        choices=["fal-ai/video-understanding", "openrouter/router/video"],
        help="Fal endpoint used for video understanding.",
    )
    parser.add_argument(
        "--video-understanding-model",
        default=None,
        help="Model name for openrouter/router/video, e.g. google/gemini-3.1-pro-preview.",
    )
    parser.add_argument("--video-understanding-max-tokens", type=int, default=64000)
    parser.add_argument("--video-understanding-temperature", type=float, default=0.2)
    parser.add_argument(
        "--reference-url",
        help="Public URL to send to Fal instead of uploading the local reference file.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Render a local animatic preview MP4 from the compiled render plan.",
    )
    parser.add_argument(
        "--preview-output",
        type=Path,
        default=Path("examples/anmer_reference_mapping/preview.mp4"),
        help="Preview MP4 output path.",
    )
    parser.add_argument("--preview-width", type=int, default=1280)
    parser.add_argument("--preview-height", type=int, default=720)
    parser.add_argument("--preview-fps", type=int, default=24)
    parser.add_argument(
        "--preview-debug-labels",
        action="store_true",
        help="Burn shot id, function, selected image, and variant mode into the preview.",
    )
    parser.add_argument(
        "--preview-no-audio",
        action="store_true",
        help="Do not attach audio from the reference MP4 to the preview.",
    )
    parser.add_argument(
        "--multimodal-compile",
        action="store_true",
        help="Run the vision-language compiler over top candidate images and apply its decisions.",
    )
    parser.add_argument(
        "--multimodal-model",
        default="google/gemini-3.1-pro-preview",
        help="Vision model for openrouter/router/vision.",
    )
    parser.add_argument(
        "--multimodal-max-candidates",
        type=int,
        default=8,
        help="Number of top candidate images to send per shot.",
    )
    parser.add_argument(
        "--multimodal-max-shots",
        type=int,
        default=None,
        help="Optional cap for testing the multimodal compiler on only the first N shots.",
    )
    parser.add_argument(
        "--multimodal-parallelism",
        type=int,
        default=1,
        help="Number of multimodal candidate image checks to run in parallel. Use 0 for all selected shots.",
    )
    parser.add_argument(
        "--r2-base-url",
        default="https://r2-public.waqaas.workers.dev",
        help="Public R2 Worker base URL for uploaded candidate images.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate real video clips from the render plan and assemble them with reference audio.",
    )
    parser.add_argument(
        "--generation-output-dir",
        type=Path,
        help="Directory for generated clips and final assembled video. Defaults to output-dir.",
    )
    parser.add_argument(
        "--generation-video-model",
        default=VIDEO_ENDPOINT_QUALITY,
        help="Fal image/reference-to-video model endpoint for final shot generation.",
    )
    parser.add_argument(
        "--generation-image-edit-model",
        default=IMAGE_EDIT_ENDPOINT,
        help="Fal image-edit model endpoint for queued ingredient variants.",
    )
    parser.add_argument(
        "--generation-resolution",
        default="720p",
        choices=["480p", "720p", "1080p"],
        help="Requested generation resolution.",
    )
    parser.add_argument(
        "--generation-max-shots",
        type=int,
        default=None,
        help="Optional cap for testing real generation on only the first N shots.",
    )
    parser.add_argument(
        "--generation-parallelism",
        type=int,
        default=1,
        help="Number of shots to enqueue/generate in parallel. Use 0 for all shots; each shot still runs image-edit before video when needed.",
    )
    parser.add_argument(
        "--no-reuse-existing-generation",
        action="store_true",
        help="Do not reuse existing generated JSON or downloaded clips.",
    )
    args = parser.parse_args()

    reference = args.reference.resolve()
    photoshoot = args.photoshoot.resolve()
    output_dir = args.output_dir
    if not reference.exists():
        raise SystemExit(f"Reference video not found: {reference}")
    if not photoshoot.exists():
        raise SystemExit(f"Photoshoot folder not found: {photoshoot}")

    style = None
    style_filename = "reference_style_template.local.json"
    render_plan_filename = "render_plan.local.json"
    loaded_plan = args.render_plan_input is not None
    if loaded_plan:
        plan_path = args.render_plan_input.resolve()
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        render_plan_filename = plan_path.name
    else:
        parsed_span_graph = None
        parsed_path = output_dir / "fal_span_graph.parsed.json"
        if args.reuse_parsed_span_graph and parsed_path.exists():
            parsed_span_graph = json.loads(parsed_path.read_text(encoding="utf-8"))
        elif args.fal_span_graph or args.ai_style:
            parsed_span_graph = fetch_fal_span_graph(
                reference,
                output_dir,
                args.reference_url,
                args.video_understanding_endpoint,
                args.video_understanding_model,
                args.video_understanding_max_tokens,
                args.video_understanding_temperature,
            )

        shot_style_fragments = None
        if args.ai_style:
            if parsed_span_graph is None and parsed_path.exists():
                parsed_span_graph = json.loads(parsed_path.read_text(encoding="utf-8"))
            if parsed_span_graph is None:
                raise SystemExit("AI style requested, but no parsed Fal span graph is available.")
            fragments_path = args.shot_style_fragments_input or (output_dir / SHOT_STYLE_FRAGMENTS_FILENAME)
            if args.shot_style_fragments_input:
                shot_style_fragments = load_shot_style_fragments(args.shot_style_fragments_input)
            elif args.reuse_shot_style_fragments and fragments_path.exists():
                shot_style_fragments = load_shot_style_fragments(fragments_path)
            elif args.shot_style_fragments:
                shot_style_fragments = extract_shot_style_fragments(
                    parsed_span_graph,
                    reference,
                    output_dir,
                    reference_url=args.reference_url,
                    endpoint=args.video_understanding_endpoint,
                    model=args.video_understanding_model or "google/gemini-3.1-pro-preview",
                    max_tokens=args.shot_style_fragments_max_tokens,
                    temperature=args.video_understanding_temperature,
                    max_shots=args.shot_style_fragments_max_shots,
                    parallelism=args.shot_style_fragments_parallelism,
                )
            style = build_ai_style_template(
                parsed_span_graph,
                reference,
                max_shots=args.ai_style_max_shots,
                shot_style_fragments=shot_style_fragments,
            )
            style_filename = "reference_style_template.ai.json"
            render_plan_filename = "render_plan.ai.json"

        artifacts = build_local_plan(reference, photoshoot, output_dir, style, style_filename, render_plan_filename)
        plan = artifacts["render_plan"]
        assert isinstance(plan, dict)

        if args.multimodal_compile:
            plan = run_multimodal_compile(
                plan,
                output_dir,
                model=args.multimodal_model,
                r2_base_url=args.r2_base_url,
                max_candidates=args.multimodal_max_candidates,
                max_shots=args.multimodal_max_shots,
                parallelism=args.multimodal_parallelism,
            )
            render_plan_filename = "render_plan.ai.multimodal.json" if args.ai_style else "render_plan.multimodal.json"
            write_json(output_dir / render_plan_filename, plan)

    if loaded_plan:
        print(f"Loaded {args.render_plan_input}")
    else:
        print(f"Wrote {output_dir / style_filename}")
        print(f"Wrote {output_dir / 'photo_inventory.local.json'}")
        print(f"Wrote {output_dir / render_plan_filename}")
    print(f"Timeline shots: {len(plan['timeline'])}")
    print(f"Duration target: {plan['durationTarget']}s")

    if args.preview:
        reference_audio = None if args.preview_no_audio else reference
        render_preview(
            plan,
            args.preview_output,
            reference_audio=reference_audio,
            width=args.preview_width,
            height=args.preview_height,
            fps=args.preview_fps,
            debug_labels=args.preview_debug_labels,
        )
        print(f"Wrote {args.preview_output}")

    if args.generate:
        generation_dir = args.generation_output_dir or output_dir
        manifest = generate_and_assemble(
            plan,
            generation_dir,
            reference,
            r2_base_url=args.r2_base_url,
            video_model=args.generation_video_model,
            image_edit_model=args.generation_image_edit_model,
            resolution=args.generation_resolution,
            max_shots=args.generation_max_shots,
            reuse_existing=not args.no_reuse_existing_generation,
            parallelism=args.generation_parallelism,
        )
        print(f"Wrote {manifest['assembledVideo']}")
        print(f"Wrote {generation_dir / 'generation_manifest.json'}")

    if not loaded_plan and (args.fal_span_graph or args.ai_style):
        print(f"Wrote {output_dir / 'fal_span_graph.raw.json'}")
        parsed_path = output_dir / "fal_span_graph.parsed.json"
        if parsed_path.exists():
            print(f"Wrote {parsed_path}")
        validation_path = output_dir / "fal_span_graph.validation.json"
        if validation_path.exists():
            print(f"Wrote {validation_path}")


if __name__ == "__main__":
    main()
