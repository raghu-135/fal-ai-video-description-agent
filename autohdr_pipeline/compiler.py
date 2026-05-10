"""Compile a StyleTemplate and PhotoInventory into a render plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .utils import clamp


SPACE_GROUPS = {
    "exterior": {"exterior", "aerial", "amenity"},
    "aerial": {"aerial", "exterior"},
    "living": {"living", "entry", "dining"},
    "kitchen": {"kitchen", "living", "detail"},
    "detail": {"detail", "kitchen", "bathroom", "amenity", "entry"},
    "bathroom": {"bathroom", "detail"},
    "bedroom": {"bedroom", "living"},
    "amenity": {"amenity", "exterior", "aerial", "garage"},
}


def movement_key(movement_type: str) -> str:
    if movement_type in {"push_in", "dolly_in", "pull_out"}:
        return "dolly_in"
    if movement_type in {"truck_right", "truck_left", "pan"}:
        return "truck_right"
    if movement_type in {"crane_up", "crane_down"}:
        return "crane_up"
    if movement_type == "drone":
        return "drone"
    return "static"


def semantic_score(asset: dict[str, Any], target_space: str) -> float:
    if asset["spaceType"] == target_space:
        return 1.0
    if asset["spaceType"] in SPACE_GROUPS.get(target_space, set()):
        return 0.72
    if target_space == "detail" and asset["shotScale"] in {"detail", "medium"}:
        return 0.58
    return 0.18


def composition_score(asset: dict[str, Any], target_scale: str) -> float:
    if asset["shotScale"] == target_scale:
        return 1.0
    if target_scale == "wide" and asset["shotScale"] in {"medium", "aerial"}:
        return 0.65
    if target_scale == "medium" and asset["shotScale"] in {"wide", "detail"}:
        return 0.62
    if target_scale == "detail" and asset["shotScale"] == "medium":
        return 0.74
    return 0.35


def choose_variant(slot: dict[str, Any], asset: dict[str, Any]) -> str:
    preferred = slot["preferredVariantMode"]
    if preferred in asset["variantPotential"]:
        return preferred
    if slot["stylisticFunction"] == "texture_detail" and "detail_crop" in asset["variantPotential"]:
        return "detail_crop"
    if "cinematic_light_variant" in asset["variantPotential"] and slot["stylisticFunction"] in {
        "feature_showcase",
        "light_moment",
        "closing_hero",
    }:
        return "cinematic_light_variant"
    if "conservative_edit" in asset["variantPotential"]:
        return "conservative_edit"
    return "raw_passthrough"


def asset_score(asset: dict[str, Any], slot: dict[str, Any], used_assets: set[str], recent_spaces: list[str]) -> dict[str, Any]:
    target = slot["contentTarget"]["spaceType"]
    movement = movement_key(slot["cameraMotion"]["movement_type"])
    semantic = semantic_score(asset, target)
    composition = composition_score(asset, slot["compositionIntent"]["shotScale"])
    motion = asset["motionSuitability"].get(movement, 0.35)
    aesthetic = float(asset.get("aestheticQuality", 0.5))
    variant_mode = choose_variant(slot, asset)
    factual_safety = 0.92 if variant_mode in {"raw_passthrough", "conservative_edit", "detail_crop"} else 0.78
    creative = 0.62
    diversity = 0.82
    if asset["id"] in used_assets:
        diversity -= 0.35
    if recent_spaces and asset["spaceType"] == recent_spaces[-1]:
        diversity -= 0.14
    if recent_spaces.count(asset["spaceType"]) >= 2:
        diversity -= 0.12
    model_risk = 0.75 if asset["geometry"]["perspectiveRisk"] == "low" else 0.58
    total = (
        semantic * 0.31
        + composition * 0.16
        + motion * 0.15
        + aesthetic * 0.11
        + factual_safety * 0.1
        + creative * 0.05
        + clamp(diversity) * 0.06
        + model_risk * 0.06
    )
    return {
        "score": round(total, 3),
        "scoreBreakdown": {
            "semantic_fit": round(semantic, 3),
            "composition_fit": round(composition, 3),
            "motion_fit": round(motion, 3),
            "style_variant_potential": 1.0 if variant_mode == slot["preferredVariantMode"] else 0.72,
            "factual_safety": round(factual_safety, 3),
            "aesthetic_quality": round(aesthetic, 3),
            "creative_preference": round(creative, 3),
            "timeline_diversity": round(clamp(diversity), 3),
            "model_risk": round(model_risk, 3),
        },
    }


def image_edit_prompt(slot: dict[str, Any], variant_mode: str) -> str | None:
    preservation = (
        "Preserve exact architecture, layout, room identity, permanent fixtures, "
        "window placement, wall geometry, and furniture positions."
    )
    if variant_mode == "weather_transform":
        return (
            "Create a second-state image for a visible weather or season transformation inspired by the reference. "
            "Preserve exact architecture, roofline, windows, doors, hardscape, lot shape, and camera angle. "
            "Only the apparent weather/season, sky, ground cover, and lighting mood may change."
        )
    if variant_mode == "staging_transform":
        return (
            "Create a second-state image for a room styling transformation inspired by the reference. "
            "Preserve walls, windows, doors, built-ins, fixtures, room identity, and camera angle. "
            "Furniture/decor may change only as a plausible staging state inside the same room."
        )
    if variant_mode == "transition_plate":
        return (
            "Create a dynamic transition plate from this image with motion-friendly framing, slight directional blur, "
            "and energetic composition. Preserve architecture and factual property features."
        )
    if variant_mode == "conservative_edit":
        return f"{preservation} Correct perspective, crop, white balance, and exposure only. Keep the property factual."
    if variant_mode == "cinematic_light_variant":
        return (
            f"{preservation} Add subtle cinematic directional light and controlled shadows without changing "
            "the room, time logic, view, or factual property features."
        )
    if variant_mode == "detail_crop":
        return (
            f"{preservation} Create a tighter architectural detail crop from this image, emphasizing texture, "
            "fixtures, cabinetry, material, or window light already present."
        )
    if variant_mode == "creative_reframe":
        return (
            f"{preservation} Reframe into a more editorial composition only if the original image supports it. "
            "Do not synthesize missing space outside the source scene."
        )
    if variant_mode == "first_last_frame_pair":
        return (
            f"{preservation} Produce a compatible ending frame for first/last-frame video generation using only "
            "a plausible crop, perspective shift, or lighting change from the source."
        )
    return None


def prompt_for(slot: dict[str, Any], asset: dict[str, Any], variant_mode: str) -> dict[str, str | None]:
    camera = slot["cameraMotion"]
    enrichment = enriched_prompt_context(slot)
    creative = creative_event_prompt(slot)
    video_prompt = (
        f"{slot['compositionIntent']['framing']}. "
        f"Use a {camera['speed']} {camera['movement_type']} camera move"
        f"{' toward ' + camera['direction'] if camera.get('direction') else ''}. "
        "Stable photorealistic architectural real estate footage, smooth parallax, balanced exposure, "
        "neutral warm color, crisp but readable shadows. Preserve all geometry and factual property details."
        f"{' Reference shot grammar: ' + enrichment if enrichment else ''}"
        f"{' Creative events to execute: ' + creative if creative else ''}"
    )
    negative_prompt = (
        "warped walls, changed windows, changed layout, invented rooms, invented amenities, "
        "fake signage, low quality, uncontrolled distortion, fisheye distortion, identity changes to architecture"
    )
    token = {
        "truck_right": "[Truck right]",
        "truck_left": "[Truck left]",
        "push_in": "[Push in]",
        "pull_out": "[Pull out]",
        "crane_up": "[Pedestal up]",
    }.get(camera["movement_type"])
    return {
        "imageEditPrompt": image_edit_prompt(slot, variant_mode),
        "videoPrompt": video_prompt,
        "negativePrompt": negative_prompt,
        "modelSpecificPrompt": f"{token} {video_prompt}" if token else None,
    }


def enriched_prompt_context(slot: dict[str, Any]) -> str | None:
    parts = []
    prompt_plan = slot.get("referencePromptPlan")
    if isinstance(prompt_plan, dict):
        for key in ["videoPrompt", "modelSpecificPrompt"]:
            value = prompt_plan.get(key)
            if isinstance(value, str) and value.strip():
                parts.append(value.strip())
                break
    transition = slot.get("transitionOut")
    if isinstance(transition, dict):
        transition_type = transition.get("type")
        transition_notes = transition.get("notes")
        if isinstance(transition_type, str) and transition_type.strip():
            parts.append(f"transition out uses {transition_type.strip()}")
        if isinstance(transition_notes, str) and transition_notes.strip():
            parts.append(transition_notes.strip())
    enrichment = slot.get("segmentStyleEnrichment")
    if isinstance(enrichment, dict):
        audio_plan = enrichment.get("audioPlan")
        if isinstance(audio_plan, dict):
            beat = audio_plan.get("beatSyncStrategy")
            if isinstance(beat, str) and beat.strip():
                parts.append(f"beat sync: {beat.strip()}")
        prompt_fragments = enrichment.get("promptFragments")
        if isinstance(prompt_fragments, list):
            for fragment in prompt_fragments[:2]:
                if isinstance(fragment, dict) and isinstance(fragment.get("text"), str):
                    parts.append(fragment["text"].strip())
    span_context = slot.get("spanContext")
    if isinstance(span_context, dict):
        notes = span_context.get("compilerNotes")
        if isinstance(notes, list):
            parts.extend(item.strip() for item in notes if isinstance(item, str) and item.strip())
    return " ".join(parts)[:1200] if parts else None


def creative_event_prompt(slot: dict[str, Any]) -> str | None:
    events = slot.get("creativeEvents")
    if not isinstance(events, list):
        return None
    parts = []
    for event in events[:4]:
        if not isinstance(event, dict):
            continue
        label = event.get("uiLabel")
        description = event.get("description")
        hint = event.get("executionHint")
        hint_notes = hint.get("notes") if isinstance(hint, dict) else None
        text = ". ".join(str(part) for part in [label, description, hint_notes] if part)
        if text:
            parts.append(text)
    return " ".join(parts)[:1400] if parts else None


def substitution_notes(slot: dict[str, Any], style: dict[str, Any]) -> list[str]:
    notes = []
    target = slot["contentTarget"]["spaceType"]
    for rule in style["substitutionPolicy"]:
        if target in " ".join(rule["substituteWith"]).lower() or slot["stylisticFunction"] in rule["preserve"]:
            notes.append(rule["notes"])
    return notes or ["No special fallback used; selected best semantic and motion match."]


def risk_notes(slot: dict[str, Any], asset: dict[str, Any], variant_mode: str) -> list[str]:
    risks = []
    if asset["spaceType"] != slot["contentTarget"]["spaceType"]:
        risks.append(
            f"Substituted {asset['spaceType']} for requested {slot['contentTarget']['spaceType']}; review stylistic fit."
        )
    if variant_mode == "cinematic_light_variant":
        risks.append("Lighting edit must remain factual and avoid changing time-of-day implications too aggressively.")
    if variant_mode in {"creative_reframe", "first_last_frame_pair"}:
        risks.append("Variant can misrepresent property if it synthesizes missing geometry; require review before generation.")
    if asset["geometry"]["perspectiveRisk"] != "low":
        risks.append("Busy geometry may increase image-to-video warping risk.")
    return risks or ["Low local risk; still requires generated-clip QA."]


def multimodal_compiler_request(slot: dict[str, Any], ranked: list[dict[str, Any]]) -> dict[str, Any]:
    """Request payload for a stronger image-aware compiler agent.

    The local scorer chooses a fallback candidate now. A multimodal compiler can
    inspect the top images directly and override asset choice, variant mode, or
    prompts before any image/video model is called.
    """
    top = []
    for item in ranked[:8]:
        asset = item["asset"]
        top.append(
            {
                "assetId": asset["id"],
                "path": asset["path"],
                "filename": asset["filename"],
                "localLabels": {
                    "spaceType": asset["spaceType"],
                    "shotScale": asset["shotScale"],
                    "featureTags": asset["featureTags"],
                    "variantPotential": asset["variantPotential"],
                },
                "localScore": item["score"],
                "scoreBreakdown": item["scoreBreakdown"],
            }
        )
    return {
        "schema": "multimodal_compiler_request.v1",
        "task": "Choose the best destination asset or processable variant for this style shot slot.",
        "shotSlot": {
            "id": slot["id"],
            "stylisticFunction": slot["stylisticFunction"],
            "contentTarget": slot["contentTarget"],
            "compositionIntent": slot["compositionIntent"],
            "cameraMotion": slot["cameraMotion"],
            "transitionOut": slot.get("transitionOut"),
            "spanContext": slot.get("spanContext"),
            "segmentStyleEnrichment": slot.get("segmentStyleEnrichment"),
            "creativeEvents": slot.get("creativeEvents"),
            "preferredVariantMode": slot["preferredVariantMode"],
        },
        "candidateAssets": top,
        "allowedDecisions": [
            "accept_local_selection",
            "choose_different_asset",
            "request_conservative_edit",
            "request_cinematic_light_variant",
            "request_creative_reframe",
            "request_detail_crop",
            "request_first_last_frame_pair",
            "request_weather_transform",
            "request_staging_transform",
            "request_transition_plate",
            "request_user_confirmation",
        ],
        "decisionSchema": {
            "selectedAssetId": "string|null",
            "ingredientVariantMode": "string",
            "reasoning": "string",
            "imageEditPrompt": "string|null",
            "riskLevel": "low|medium|high",
            "requiresHumanReview": "boolean",
        },
    }


def compile_render_plan(style: dict[str, Any], inventory: dict[str, Any]) -> dict[str, Any]:
    assets = inventory["sourceAssets"]
    used_assets: set[str] = set()
    recent_spaces: list[str] = []
    timeline = []
    for slot in style["shotSlots"]:
        ranked = []
        for asset in assets:
            scored = asset_score(asset, slot, used_assets, recent_spaces)
            ranked.append({"asset": asset, **scored})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        chosen = ranked[0]
        asset = chosen["asset"]
        used_assets.add(asset["id"])
        recent_spaces = (recent_spaces + [asset["spaceType"]])[-4:]
        variant_mode = choose_variant(slot, asset)
        prompts = prompt_for(slot, asset, variant_mode)
        timeline.append(
            {
                "shotSlotId": slot["id"],
                "referenceTimeRange": slot["referenceTimeRange"],
                "timeRange": slot["timeRange"],
                "stylisticFunction": slot["stylisticFunction"],
                "selectedAsset": {
                    "id": asset["id"],
                    "path": asset["path"],
                    "filename": asset["filename"],
                    "spaceType": asset["spaceType"],
                    "shotScale": asset["shotScale"],
                    "featureTags": asset["featureTags"],
                },
                "ingredientVariantMode": variant_mode,
                "selectionTrace": {
                    "topCandidates": [
                        {
                            "assetId": item["asset"]["id"],
                            "filename": item["asset"]["filename"],
                            "spaceType": item["asset"]["spaceType"],
                            "score": item["score"],
                            "reasons": [
                                f"semantic={item['scoreBreakdown']['semantic_fit']}",
                                f"motion={item['scoreBreakdown']['motion_fit']}",
                                f"composition={item['scoreBreakdown']['composition_fit']}",
                            ],
                        }
                        for item in ranked[:5]
                    ],
                    "scoreBreakdown": chosen["scoreBreakdown"],
                    "fallbacksConsidered": substitution_notes(slot, style),
                    "remainingRisks": risk_notes(slot, asset, variant_mode),
                },
                "multimodalCompilerRequest": multimodal_compiler_request(slot, ranked),
                "creativeEvents": slot.get("creativeEvents", []),
                "ingredientRequest": {
                    "mode": variant_mode,
                    "prompt": prompts["imageEditPrompt"],
                    "preservationConstraints": [
                        "do not change architecture",
                        "do not change layout",
                        "do not invent amenities",
                        "do not add people",
                        "keep edits auditable",
                    ],
                    "riskLevel": "medium" if variant_mode in {"cinematic_light_variant", "creative_reframe"} else "low",
                },
                "videoGeneration": {
                    "model": "bytedance/seedance-2.0/image-to-video",
                    "prompt": prompts["videoPrompt"],
                    "negativePrompt": prompts["negativePrompt"],
                    "modelSpecificPrompt": prompts["modelSpecificPrompt"],
                    "creativeEvents": slot.get("creativeEvents", []),
                    "duration": slot["timeRange"]["duration"],
                    "aspectRatio": "16:9",
                    "generateAudio": False,
                },
                "assembly": {
                    "transitionOut": slot["transitionOut"],
                    "beatLock": True,
                    "spanContext": slot.get("spanContext"),
                    "creativeEvents": slot.get("creativeEvents", []),
                    "trimNotes": "generate at nearest supported model duration and trim to this slot range",
                },
                "qualityChecks": [
                    "source geometry is preserved",
                    "room identity is preserved",
                    "no invented exterior/environmental features",
                    "camera motion matches shot slot",
                    "clip is sharp enough for real estate use",
                ]
                + slot.get("qualityChecksFromReference", []),
            }
        )
    return {
        "schema": "render_plan.local.v1",
        "id": f"{Path(inventory['sourceFolder']).name}_mapped_to_reference_style",
        "durationTarget": round(sum(slot["timeRange"]["duration"] for slot in style["shotSlots"]), 3),
        "styleTemplateId": style["id"],
        "sourceFolder": inventory["sourceFolder"],
        "timeline": timeline,
        "agentOrchestrationTrace": [
            "timeline_analyzer: probe reference metadata and cut candidates",
            "span_graph_agent: planned Fal full-video span extraction",
            "span_style_agent: planned Fal segment style extraction",
            "style_merger_agent: currently loads local reference blueprint",
            "photoshoot_inventory_agent: classifies destination images and variant potential",
            "selection_compiler_agent: scores assets against style shot slots",
            "multimodal_compiler_agent: hook can inspect candidate images and override local scoring",
            "ingredient_planner_agent: selects raw/edit/detail/first-last variant mode",
            "prompt_compiler_agent: emits per-shot image/video/negative prompts",
        ],
    }
