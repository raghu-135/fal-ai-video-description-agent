"""StyleTemplate construction."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .blueprint import STYLE_BLUEPRINT
from .utils import probe_video


def build_local_style_template(reference_video: Path) -> dict[str, Any]:
    metadata = probe_video(reference_video)
    shot_slots = []
    cursor = 0.0
    for blueprint in STYLE_BLUEPRINT:
        duration = blueprint["duration"]
        start = cursor
        end = cursor + duration
        cursor = end
        shot_slots.append(
            {
                "id": blueprint["id"],
                "referenceTimeRange": {"start": blueprint["reference_time"][0], "end": blueprint["reference_time"][1]},
                "timeRange": {"start": round(start, 3), "end": round(end, 3), "duration": duration},
                "stylisticFunction": blueprint["stylistic_function"],
                "musicAnchor": {"type": "beat", "timestamp": round(end, 3), "lockToBeat": True},
                "contentTarget": {
                    "spaceType": blueprint["space_type"],
                    "featureTags": blueprint["features"],
                    "transferability": "adaptable_content",
                    "substitutionNotes": "Preserve stylistic function before literal reference content.",
                },
                "compositionIntent": {
                    "shotScale": blueprint["shot_scale"],
                    "viewpoint": blueprint["composition"],
                    "framing": blueprint["composition"],
                    "lensFeel": "wide architectural lens for orientation; tighter editorial crop for details",
                },
                "cameraMotion": blueprint["camera"],
                "lightingMotion": {
                    "type": "timelapse_or_shadow_shift" if blueprint["variant_mode"] == "cinematic_light_variant" else "none",
                    "notes": "Subtle light travel is preferred when it does not misrepresent the property.",
                },
                "visualTreatment": {
                    "color": "neutral warm architectural color",
                    "contrast": "crisp contrast with readable shadows",
                    "whiteBalance": "neutral",
                    "shadowStrategy": "deep but not underexposed",
                },
                "transitionOut": {"type": blueprint["transition_out"], "notes": "Cut should feel locked to music cadence."},
                "preferredVariantMode": blueprint["variant_mode"],
            }
        )

    return {
        "schema": "style_template.local_blueprint.v1",
        "id": "reference_mp4_cinematic_real_estate_style",
        "version": "0.1",
        "referenceVideo": metadata,
        "globalStyle": {
            "mood": ["cinematic", "editorial", "polished", "architectural"],
            "pacing": "fast hero intro, controlled interior reveals, short detail accents, exterior closing hero",
            "cameraGrammar": ["slow drone reveals", "smooth lateral slides", "push-ins", "crane/pull-out hero beats"],
            "lightingDoctrine": ["balanced exposure", "directional light when safe", "shadow movement as a style accent"],
            "colorDoctrine": ["neutral white balance", "contrast-rich but readable", "avoid flat HDR look"],
            "editingGrammar": ["short beat-locked cuts", "hard cuts and light flash accents", "detail beats between orientation shots"],
            "negativeConstraints": [
                "no warped architecture",
                "no changing room layout",
                "no invented amenities",
                "no furniture morphing",
                "no fake text or signage",
                "no people unless already present",
            ],
        },
        "spanGraph": [
            {
                "id": "whole_video",
                "type": "whole_video",
                "timeRange": {"start": 0, "end": metadata["duration_seconds"]},
                "fields": [
                    {
                        "field": "visual_doctrine",
                        "value": "cinematic architectural real estate, hero exteriors, controlled interior reveals, detail beats, confident transitions",
                        "strength": 0.9,
                        "appliesTo": ["all_shots"],
                        "source": "human_blueprint",
                        "confidence": 0.75,
                    }
                ],
                "confidence": 0.75,
                "source": "human_blueprint",
            }
        ],
        "shotSlots": shot_slots,
        "substitutionPolicy": [
            {
                "missingReferenceContent": "mountain or ski setting",
                "preserve": "establishing_hero",
                "substituteWith": ["aerial lot view", "front elevation", "neighborhood context"],
                "notes": "Do not invent mountains, snow, or ski-house context.",
            },
            {
                "missingReferenceContent": "fireplace or luxury texture",
                "preserve": "texture_detail",
                "substituteWith": ["cabinetry", "stone", "wood floor", "stair rail", "vanity", "window light"],
                "notes": "Use equivalent detail role, not fake features.",
            },
            {
                "missingReferenceContent": "large scenic view",
                "preserve": "amenity_proof",
                "substituteWith": ["yard", "patio", "outdoor living", "landscaping", "aerial context"],
                "notes": "Keep the value-expansion function.",
            },
        ],
        "modelPreferences": {
            "recommendedVideoModels": [
                "bytedance/seedance-2.0/image-to-video",
                "fal-ai/kling-video/v2.5-turbo/pro/image-to-video",
                "fal-ai/minimax/video-01-director/image-to-video",
            ],
            "durationStrategy": "generate at supported model duration and trim to the beat-locked render plan",
            "generateAudio": False,
        },
    }

