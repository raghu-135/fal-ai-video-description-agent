# AutoHDR Style Pipeline

This repo is now structured around a style-transfer pipeline, not only a video-description call.

## Product Flow

1. A creator uploads a finished reference video.
2. `span_graph_agent` runs Fal video understanding over the full video and splits it into overlapping spans: whole video, music phrase, property section, shot group, shot, transition, and micro event.
3. `span_style_agent` runs on selected spans and extracts reusable StyleTemplate fragments.
4. `style_merger_agent` merges fragments into one `StyleTemplate`.
5. An end user uploads a destination photoshoot.
6. `photoshoot_inventory_agent` analyzes every photo as raw processable material, not final clips.
7. `selection_compiler_agent` scores candidate photos against each shot slot.
8. `multimodal_compiler_agent` can inspect the top candidate images and override the local score, choose a different asset, or request an ingredient variant.
9. `ingredient_planner_agent` requests a raw pass-through, conservative edit, cinematic light variant, creative reframe, detail crop, first/last-frame pair, or transition plate.
10. `prompt_compiler_agent` emits image-edit prompts, video prompts, negative prompts, model settings, and assembly instructions.
11. `generation_orchestrator` calls Fal image-edit and image-to-video models.
12. `quality_agent` rejects generated clips with architecture changes, invented amenities, warped geometry, fake signage, or unusable blur.
13. `assembly_agent` trims clips to the timeline, applies transitions, syncs to music, and exports MP4 plus an editable project JSON.

## Why Destination Photos Stay Processable

`photo_inventory.local.json` stores each source image with `variantPotential`. The compiler does not assume the raw photo is final. Each render-plan shot includes:

- `selectedAsset`: the local fallback selection.
- `ingredientVariantMode`: how the source should be transformed before video generation.
- `ingredientRequest`: preservation constraints and optional image-edit prompt.
- `multimodalCompilerRequest`: the handoff payload for a stronger image-aware compiling agent.
- `selectionTrace`: top candidates, scores, fallback notes, and remaining risks.

This means a reasoning agent can still look at the actual images, decide that the local heuristic picked the wrong shot, request a crop/reframe/light variant, or ask for human confirmation.

## Current Local MVP

The current implementation uses:

- `autohdr_pipeline/style_template.py`: local reference style blueprint.
- `autohdr_pipeline/photo_inventory.py`: local photo classifier.
- `autohdr_pipeline/compiler.py`: asset scoring, variant planning, prompt compilation.
- `autohdr_pipeline/preview_renderer.py`: local animatic renderer for previewing shot order, pacing, rough motion, and audio before model generation.
- `autohdr_pipeline/fal_tools.py`: Fal video-understanding wrapper for the next model-backed extraction step.
- `autohdr_pipeline/prompts.py`: full-video span prompt and span-to-style-fragment prompt.

Run:

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

To also call Fal for the full-video span graph:

```bash
FAL_KEY=... python -m autohdr_pipeline.pipeline --fal-span-graph
```

Do not commit `.env` or raw API keys.

To run the model-configurable Fal route with Gemini 3.1 Pro Preview:

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

This path calls Fal/OpenRouter for video understanding, converts the parsed span graph into `reference_style_template.ai.json`, compiles `render_plan.ai.json`, and renders an AI-derived preview.

To preview a possible final output without image-to-video generation:

```bash
python -m autohdr_pipeline.pipeline --preview
```

The preview uses the render plan's selected photos, applies rough pan/zoom motion per shot, and attaches the reference MP4 audio if present. It is meant to validate pacing and mapping decisions, not final generation quality.
