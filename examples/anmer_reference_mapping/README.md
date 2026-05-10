# Anmer Reference Mapping

Generated with:

```bash
python -m autohdr_pipeline.pipeline
```

Inputs:

- Reference video: `../SnapInsta-Ai_3827468812233464997.mp4`
- Destination photoshoot: `../video-hackathon-public/216_Anmer_Hall_Fort_Wayne_IN_46845`

Outputs:

- `reference_style_template.local.json`: local style blueprint for the reference MP4.
- `photo_inventory.local.json`: destination photo inventory with source image labels and `variantPotential`.
- `render_plan.local.json`: 12-shot mapped timeline with local asset selections, ingredient requests, prompts, model settings, quality checks, and `multimodalCompilerRequest` payloads.
- `preview.mp4`: clean local animatic preview from the render plan.
- `preview_debug.mp4`: lower-res labeled preview for inspecting shot-slot mappings.
- `reference_style_template.ai.json`: style template compiled from the Gemini/Fal span graph.
- `render_plan.ai.json`: render plan compiled from the AI-derived style template.
- `preview_ai_gemini31.mp4`: labeled preview compiled from the Gemini 3.1 Pro Preview extraction.
- `fal_span_graph.raw.json`, `fal_span_graph.parsed.json`, `fal_span_graph.validation.json`: raw model response, parsed JSON, and deterministic validation.

The local selections are fallbacks. A stronger multimodal compiler can inspect each shot's candidate assets and override the selected photo, variant mode, and image-edit prompt before generation.
