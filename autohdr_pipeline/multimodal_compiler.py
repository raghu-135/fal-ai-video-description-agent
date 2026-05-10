"""Multimodal render-plan compiler.

This stage lets a vision-language model inspect actual destination photos and
override local heuristic asset selection before image/video generation.
"""

from __future__ import annotations

import json
import mimetypes
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .compiler import prompt_for
from .fal_tools import FalVideoUnderstandingAgent
from .utils import write_json


ALLOWED_VARIANTS = {
    "raw_passthrough",
    "conservative_edit",
    "cinematic_light_variant",
    "creative_reframe",
    "detail_crop",
    "first_last_frame_pair",
    "transition_plate",
    "weather_transform",
    "staging_transform",
}


def run_multimodal_compile(
    render_plan: dict[str, Any],
    output_dir: Path,
    *,
    model: str = "google/gemini-3.1-pro-preview",
    r2_base_url: str = "https://r2-public.waqaas.workers.dev",
    max_candidates: int = 8,
    max_shots: int | None = None,
    parallelism: int = 1,
) -> dict[str, Any]:
    decisions = []
    asset_cache: dict[str, dict[str, Any]] = {}
    previous_ingredients: list[dict[str, Any]] = []
    timeline = render_plan["timeline"]
    selected_timeline = timeline[:max_shots] if max_shots else timeline
    parallelism = len(selected_timeline) if parallelism <= 0 else parallelism
    job_prefix = f"autohdr-multimodal/{safe_id(render_plan['id'])}/{int(time.time())}"

    if parallelism > 1:
        print(f"[multimodal] parallelism={parallelism}", flush=True)
        prepared = [
            prepare_multimodal_item(
                item,
                index,
                len(selected_timeline),
                asset_cache,
                job_prefix,
                r2_base_url,
                max_candidates,
                previous_ingredients=[],
            )
            for index, item in enumerate(selected_timeline, 1)
        ]
        results_by_index: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=parallelism) as executor:
            futures = {
                executor.submit(run_multimodal_model_call, task["imageUrls"], task["prompt"], model): task["index"]
                for task in prepared
            }
            for future in as_completed(futures):
                index = futures[future]
                results_by_index[index] = future.result()
                print(f"[multimodal] model result {index}/{len(selected_timeline)}", flush=True)

        for task in prepared:
            result_record = results_by_index[task["index"]]
            item = task["item"]
            decision = normalize_decision(result_record["parsed"], task["candidates"], item, previous_ingredients)
            apply_decision(item, decision, task["candidates"])
            previous_ingredients.append(previous_ingredient_record(item, decision))
            decisions.append(
                {
                    "shotSlotId": item["shotSlotId"],
                    "model": model,
                    "imageUrls": task["imageUrls"],
                    "rawResult": result_record["rawResult"],
                    "parsedDecision": result_record["parsed"],
                    "appliedDecision": decision,
                }
            )
            print(
                f"[multimodal] apply {task['index']}/{len(selected_timeline)} {item['shotSlotId']} "
                f"-> {decision['selectedAssetId']} {decision['ingredientVariantMode']}",
                flush=True,
            )
    else:
        agent = FalVideoUnderstandingAgent()
        for index, item in enumerate(selected_timeline, 1):
            task = prepare_multimodal_item(
                item,
                index,
                len(selected_timeline),
                asset_cache,
                job_prefix,
                r2_base_url,
                max_candidates,
                previous_ingredients=previous_ingredients,
            )
            result = agent.analyze_images(
                task["imageUrls"],
                task["prompt"],
                model=model,
                system_prompt="You are a strict real-estate video style compiler. Return valid JSON only.",
                reasoning=True,
                temperature=0.1,
                max_tokens=12000,
            )
            parsed = agent.parsed_output_json(result)
            decision = normalize_decision(parsed, task["candidates"], item, previous_ingredients)
            apply_decision(item, decision, task["candidates"])
            previous_ingredients.append(previous_ingredient_record(item, decision))
            decisions.append(
                {
                    "shotSlotId": item["shotSlotId"],
                    "model": model,
                    "imageUrls": task["imageUrls"],
                    "rawResult": result,
                    "parsedDecision": parsed,
                    "appliedDecision": decision,
                }
            )
            print(
                f"[multimodal] {index}/{len(selected_timeline)} {item['shotSlotId']} "
                f"-> {decision['selectedAssetId']} {decision['ingredientVariantMode']}",
                flush=True,
            )

    render_plan["schema"] = "render_plan.multimodal_compiled.v1"
    render_plan["multimodalCompiler"] = {
        "model": model,
        "compiledShotCount": len(selected_timeline),
        "parallelism": parallelism,
        "r2Prefix": job_prefix,
        "notes": [
            "Selected assets and ingredient variants were reviewed by a vision-language model.",
            "Raw model decisions are preserved in multimodal_compiler_decisions.json.",
        ],
    }
    render_plan["ingredientRequests"] = build_ingredient_request_queue(render_plan["timeline"])
    write_json(output_dir / "multimodal_compiler_decisions.json", {"schema": "multimodal_compiler_decisions.v1", "decisions": decisions})
    return render_plan


def prepare_multimodal_item(
    item: dict[str, Any],
    index: int,
    total: int,
    asset_cache: dict[str, dict[str, Any]],
    job_prefix: str,
    r2_base_url: str,
    max_candidates: int,
    previous_ingredients: list[dict[str, Any]],
) -> dict[str, Any]:
    request = item["multimodalCompilerRequest"]
    candidates = request["candidateAssets"][:max_candidates]
    image_urls = []
    candidate_records = []
    for candidate_index, candidate in enumerate(candidates, 1):
        path = Path(candidate["path"])
        asset_id = candidate["assetId"]
        cache_key = f"{asset_id}:{path}"
        if cache_key not in asset_cache:
            key = f"{job_prefix}/{asset_id}.jpg"
            url = upload_resized_image(path, r2_base_url, key)
            asset_cache[cache_key] = {"url": url, "r2Key": key}
        public = asset_cache[cache_key]
        image_urls.append(public["url"])
        candidate_records.append(
            {
                "index": candidate_index,
                "assetId": asset_id,
                "filename": candidate["filename"],
                "imageUrl": public["url"],
                "localLabels": candidate["localLabels"],
                "localScore": candidate["localScore"],
                "scoreBreakdown": candidate["scoreBreakdown"],
            }
        )
    prompt = build_multimodal_prompt(request, candidate_records, item, previous_ingredients)
    return {
        "index": index,
        "total": total,
        "item": item,
        "candidates": candidates,
        "imageUrls": image_urls,
        "prompt": prompt,
    }


def run_multimodal_model_call(image_urls: list[str], prompt: str, model: str) -> dict[str, Any]:
    import time

    agent = FalVideoUnderstandingAgent()
    error = None
    for attempt in range(1, 4):
        try:
            result = agent.analyze_images(
                image_urls,
                prompt,
                model=model,
                system_prompt="You are a strict real-estate video style compiler. Return valid JSON only.",
                reasoning=True,
                temperature=0.1,
                max_tokens=12000,
            )
            return {"rawResult": result, "parsed": agent.parsed_output_json(result), "error": None}
        except Exception as exc:
            error = str(exc)
            if attempt < 3:
                time.sleep(2 * attempt)
    return {"rawResult": {"error": error}, "parsed": None, "error": error}


def previous_ingredient_record(item: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    return {
        "shotSlotId": item["shotSlotId"],
        "sourceAssetId": decision["selectedAssetId"],
        "ingredientVariantMode": decision["ingredientVariantMode"],
        "ingredientVariantId": item["ingredientVariantId"],
        "stylisticFunction": item["stylisticFunction"],
        "variationSummary": decision.get("variantPurpose"),
    }


def build_multimodal_prompt(
    request: dict[str, Any],
    candidates: list[dict[str, Any]],
    item: dict[str, Any],
    previous_ingredients: list[dict[str, Any]],
) -> str:
    shot_slot = request["shotSlot"]
    return (
        "You are choosing the best destination real-estate photo or processable image variant for a style shot slot.\n"
        "You can inspect the candidate images in the exact order listed below. The first image corresponds to candidate index 1, etc.\n\n"
        "Goal: preserve the reference shot's stylistic function while staying factual to the destination property.\n"
        "Do not request edits that invent architecture, amenities, views, rooms, signage, or square footage. "
        "When SHOT_SLOT.creativeEvents calls for weather/season, staging, speed-ramp, whip, or transform behavior, keep that creative behavior as a first-class requirement. "
        "Use weather_transform or staging_transform when the reference requires a visible state change and the candidate can plausibly support it. "
        "People/lifestyle subjects are allowed only when the SHOT_SLOT explicitly includes people, skiers, social activity, or lifestyle/human activity.\n"
        "Prefer a source image that can support the requested camera move with minimal warping risk.\n\n"
        f"SHOT_SLOT:\n{json.dumps(shot_slot, indent=2)}\n\n"
        f"LOCAL_SELECTION:\n{json.dumps(item['selectedAsset'], indent=2)}\n"
        f"LOCAL_VARIANT_MODE: {item['ingredientVariantMode']}\n\n"
        f"PREVIOUS_INGREDIENTS:\n{json.dumps(previous_ingredients, indent=2)}\n"
        "A raw source photo may be reused only when it becomes a meaningfully different IngredientVariant: "
        "for example a detail crop, cinematic light variant, creative reframe, first/last-frame endpoint, or different shot function. "
        "Avoid repeated raw_passthrough use of the same source asset. If reusing a source asset, provide a specific imageEditPrompt and explain the variation.\n\n"
        f"CANDIDATES:\n{json.dumps(candidates, indent=2)}\n\n"
        "Allowed ingredientVariantMode values: raw_passthrough, conservative_edit, cinematic_light_variant, "
        "creative_reframe, detail_crop, first_last_frame_pair, transition_plate, weather_transform, staging_transform.\n\n"
        "Return only valid JSON with this exact shape:\n"
        "{\n"
        '  "selectedAssetId": "asset id from candidates or null",\n'
        '  "ingredientVariantMode": "allowed variant mode",\n'
        '  "confidence": 0.0,\n'
        '  "reasoningSummary": "brief visible-image-based explanation",\n'
        '  "imageEditPrompt": "prompt or null",\n'
        '  "variantPurpose": "how this ingredient variant differs from the raw source or previous use",\n'
        '  "significantVariationFromPreviousUse": false,\n'
        '  "riskLevel": "low|medium|high",\n'
        '  "requiresHumanReview": false,\n'
        '  "rejectReasons": ["string"],\n'
        '  "qualityChecks": ["string"]\n'
        "}\n"
    )


def normalize_decision(
    parsed: dict[str, Any] | None,
    candidates: list[dict[str, Any]],
    item: dict[str, Any],
    previous_ingredients: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {candidate["assetId"] for candidate in candidates}
    fallback_asset = item["selectedAsset"]["id"]
    fallback_variant = item["ingredientVariantMode"]
    parsed = parsed if isinstance(parsed, dict) else {}
    selected = parsed.get("selectedAssetId")
    if selected not in candidate_ids:
        selected = fallback_asset if fallback_asset in candidate_ids else candidates[0]["assetId"]
    variant = parsed.get("ingredientVariantMode")
    if variant not in ALLOWED_VARIANTS:
        variant = fallback_variant if fallback_variant in ALLOWED_VARIANTS else "raw_passthrough"
    previous_for_asset = [entry for entry in previous_ingredients if entry["sourceAssetId"] == selected]
    if previous_for_asset and not reuse_is_meaningful(parsed, variant):
        used_asset_ids = {entry["sourceAssetId"] for entry in previous_ingredients}
        alternate = next((candidate["assetId"] for candidate in candidates if candidate["assetId"] not in used_asset_ids), None)
        if alternate:
            selected = alternate
            parsed["reasoningSummary"] = (
                f"Post-processed to avoid repeated raw/similar ingredient; selected {alternate} from available candidates. "
                + str(parsed.get("reasoningSummary") or "")
            )
    prompt = parsed.get("imageEditPrompt")
    if not isinstance(prompt, str) or not prompt.strip() or prompt.strip().lower() == "null":
        prompt = None
    risk = parsed.get("riskLevel")
    if risk not in {"low", "medium", "high"}:
        risk = "medium" if variant in {"cinematic_light_variant", "creative_reframe", "first_last_frame_pair"} else "low"
    decision = {
        "selectedAssetId": selected,
        "ingredientVariantMode": variant,
        "confidence": parsed.get("confidence") if isinstance(parsed.get("confidence"), (int, float)) else None,
        "reasoningSummary": parsed.get("reasoningSummary") if isinstance(parsed.get("reasoningSummary"), str) else "Model decision unavailable; used fallback.",
        "imageEditPrompt": prompt,
        "variantPurpose": parsed.get("variantPurpose") if isinstance(parsed.get("variantPurpose"), str) else None,
        "significantVariationFromPreviousUse": bool(parsed.get("significantVariationFromPreviousUse")),
        "riskLevel": risk,
        "requiresHumanReview": bool(parsed.get("requiresHumanReview", risk == "high")),
        "rejectReasons": parsed.get("rejectReasons") if isinstance(parsed.get("rejectReasons"), list) else [],
        "qualityChecks": parsed.get("qualityChecks") if isinstance(parsed.get("qualityChecks"), list) else [],
    }
    return enforce_real_estate_guardrails(decision, item)


def reuse_is_meaningful(parsed: dict[str, Any], variant: str) -> bool:
    if variant == "raw_passthrough":
        return False
    prompt = parsed.get("imageEditPrompt")
    has_prompt = isinstance(prompt, str) and prompt.strip() and prompt.strip().lower() != "null"
    return bool(parsed.get("significantVariationFromPreviousUse")) or has_prompt


def enforce_real_estate_guardrails(decision: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    prompt = decision.get("imageEditPrompt") or ""
    lowered = prompt.lower()
    banned_people = ["add people", "add a person", "add persons", "add family", "add humans", "people relaxing"]
    invented_risk_terms = ["add a pool", "add pool", "add fireplace", "add mountain", "add ocean", "add lake"]
    reject_reasons = list(decision.get("rejectReasons") or [])

    if any(term in lowered for term in banned_people):
        if reference_allows_people(item):
            decision["riskLevel"] = max_risk(decision.get("riskLevel"), "medium")
            quality_checks = list(decision.get("qualityChecks") or [])
            quality_checks.append("Any added people must match the reference lifestyle function and look natural, non-identifying, and physically plausible.")
            quality_checks.append("Do not let lifestyle subjects obscure architecture, layout, fixtures, or factual property features.")
            decision["qualityChecks"] = quality_checks
        else:
            reject_reasons.append("Removed request to add people because this reference shot slot does not call for people or lifestyle activity.")
            decision["imageEditPrompt"] = safe_image_edit_prompt(decision["ingredientVariantMode"], allow_people=False)
            decision["riskLevel"] = "high"
            decision["requiresHumanReview"] = True

    if any(term in lowered for term in invented_risk_terms):
        reject_reasons.append("Removed request that could invent a non-existent property feature.")
        decision["imageEditPrompt"] = safe_image_edit_prompt(decision["ingredientVariantMode"], allow_people=reference_allows_people(item))
        decision["riskLevel"] = "high"
        decision["requiresHumanReview"] = True

    if any(term in lowered for term in ["snow", "winter", "season", "weather"]) and reference_allows_weather_transform(item):
        decision["riskLevel"] = max_risk(decision.get("riskLevel"), "medium")
        quality_checks = list(decision.get("qualityChecks") or [])
        quality_checks.append("Weather/season transformation must preserve architecture and read as a creative transition effect.")
        decision["qualityChecks"] = quality_checks

    if any(term in lowered for term in ["twilight", "sunset", "golden hour"]) and decision["riskLevel"] == "low":
        reject_reasons.append("Time-of-day lighting change should be reviewed for listing-safe use.")
        decision["riskLevel"] = "medium"
        decision["requiresHumanReview"] = True

    decision["rejectReasons"] = reject_reasons
    return decision


def reference_allows_people(item: dict[str, Any]) -> bool:
    shot_slot = item.get("multimodalCompilerRequest", {}).get("shotSlot", {})
    text = json.dumps(shot_slot).lower() + " " + str(item.get("stylisticFunction", "")).lower()
    people_terms = ["people", "person", "human", "family", "lifestyle", "social", "skier", "skiers", "guest", "activity"]
    return any(term in text for term in people_terms)


def reference_allows_weather_transform(item: dict[str, Any]) -> bool:
    shot_slot = item.get("multimodalCompilerRequest", {}).get("shotSlot", {})
    text = json.dumps(shot_slot).lower()
    return any(term in text for term in ["weather", "season", "winter", "snow", "autumn", "fall"])


def max_risk(current: Any, minimum: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    current = current if current in order else "low"
    return current if order[current] >= order[minimum] else minimum


def safe_image_edit_prompt(variant_mode: str, allow_people: bool = False) -> str:
    people_rule = (
        "People may be included only as non-identifying lifestyle subjects when required by the reference shot."
        if allow_people
        else "Do not add people."
    )
    base = (
        "Preserve exact architecture, layout, room identity, permanent fixtures, window placement, "
        f"wall geometry, views, furniture, and factual property features. {people_rule} Do not add amenities."
    )
    if variant_mode == "detail_crop":
        return base + " Create a tighter crop of details already visible in the source image."
    if variant_mode == "cinematic_light_variant":
        return base + " Apply subtle cinematic contrast and directional light only from plausible existing light sources."
    if variant_mode == "weather_transform":
        return (
            "Preserve exact architecture, roofline, windows, doors, hardscape, lot shape, and camera angle. "
            "Create only an apparent weather/season transformation: sky, ground cover, atmospheric light, and color temperature may change."
        )
    if variant_mode == "staging_transform":
        return (
            "Preserve walls, windows, doors, built-ins, fixtures, room identity, and camera angle. "
            "Furniture/decor may change only as a plausible staged state inside the same room."
        )
    if variant_mode == "transition_plate":
        return base + " Add motion-friendly directional blur or energetic framing for a transition plate."
    if variant_mode == "creative_reframe":
        return base + " Reframe using only pixels and geometry plausibly supported by the source image."
    return base + " Apply only conservative exposure, crop, perspective, and color corrections."


def apply_decision(item: dict[str, Any], decision: dict[str, Any], candidates: list[dict[str, Any]]) -> None:
    candidate_by_id = {candidate["assetId"]: candidate for candidate in candidates}
    candidate = candidate_by_id[decision["selectedAssetId"]]
    local = candidate["localLabels"]
    item["selectedAsset"] = {
        "id": candidate["assetId"],
        "path": candidate["path"],
        "filename": candidate["filename"],
        "spaceType": local["spaceType"],
        "shotScale": local["shotScale"],
        "featureTags": local["featureTags"],
    }
    item["ingredientVariantMode"] = decision["ingredientVariantMode"]
    item["ingredientVariantId"] = f"{item['shotSlotId']}__{candidate['assetId']}__{decision['ingredientVariantMode']}"
    slot = item["multimodalCompilerRequest"]["shotSlot"]
    prompt_slot = dict(slot)
    prompt_slot["preferredVariantMode"] = decision["ingredientVariantMode"]
    prompts = prompt_for(prompt_slot, item["selectedAsset"], decision["ingredientVariantMode"])
    if decision["imageEditPrompt"]:
        prompts["imageEditPrompt"] = decision["imageEditPrompt"]
    item["ingredientRequest"]["mode"] = decision["ingredientVariantMode"]
    item["ingredientRequest"]["prompt"] = prompts["imageEditPrompt"]
    item["ingredientRequest"]["riskLevel"] = decision["riskLevel"]
    item["videoGeneration"]["prompt"] = prompts["videoPrompt"]
    item["videoGeneration"]["negativePrompt"] = prompts["negativePrompt"]
    item["videoGeneration"]["modelSpecificPrompt"] = prompts["modelSpecificPrompt"]
    item["videoGeneration"]["creativeEvents"] = slot.get("creativeEvents", [])
    item["creativeEvents"] = slot.get("creativeEvents", [])
    item["selectionTrace"]["multimodalDecision"] = decision
    item["qualityChecks"] = merge_quality_checks(item.get("qualityChecks", []), decision.get("qualityChecks", []))


def build_ingredient_request_queue(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    requests = []
    for item in timeline:
        mode = item.get("ingredientVariantMode")
        ingredient_id = item.get("ingredientVariantId") or f"{item['shotSlotId']}__{item['selectedAsset']['id']}__{mode}"
        request = {
            "id": ingredient_id,
            "shotSlotId": item["shotSlotId"],
            "sourceAsset": item["selectedAsset"],
            "mode": mode,
            "status": "not_required" if mode == "raw_passthrough" else "queued",
            "prompt": item.get("ingredientRequest", {}).get("prompt"),
            "variantPurpose": item.get("selectionTrace", {}).get("multimodalDecision", {}).get("variantPurpose"),
            "preservationConstraints": item.get("ingredientRequest", {}).get("preservationConstraints", []),
            "riskLevel": item.get("ingredientRequest", {}).get("riskLevel", "low"),
            "requiresHumanReview": item.get("selectionTrace", {}).get("multimodalDecision", {}).get("requiresHumanReview", False),
        }
        requests.append(request)
        item["ingredientVariantId"] = ingredient_id
    return requests


def merge_quality_checks(existing: list[str], added: list[str]) -> list[str]:
    merged = list(existing)
    for item in added:
        if isinstance(item, str) and item not in merged:
            merged.append(item)
    return merged


def upload_resized_image(path: Path, base_url: str, key: str, max_edge: int = 1600, quality: int = 88) -> str:
    with Image.open(path) as raw:
        image = ImageOps.exif_transpose(raw).convert("RGB")
        image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
    url = f"{base_url.rstrip('/')}/{key}"
    request = urllib.request.Request(
        url,
        data=buffer.getvalue(),
        method="PUT",
        headers={
            "Content-Type": mimetypes.types_map.get(".jpg", "image/jpeg"),
            "User-Agent": "curl/8.0.0",
        },
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status >= 300:
            raise RuntimeError(f"R2 upload failed for {path}: HTTP {response.status}")
    return url


def safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in value)[:80]
