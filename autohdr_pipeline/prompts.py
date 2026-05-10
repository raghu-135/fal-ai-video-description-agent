"""Prompts for model-assisted reference video style extraction."""

FULL_VIDEO_SPAN_PROMPT = """
You are analyzing a finished real estate reference video so its creative editing
style can become a reusable structured style template.

Break the video into overlapping spans: whole_video, music_phrase,
property_section, shot_group, shot, transition, and micro_event. Describe why
each span exists in the edit, not only what is visible. Separate transferable
style from reference-specific content.

Use transferability values:
style_invariant, adaptable_content, reference_specific.

Use stylistic functions:
establishing_hero, arrival, property_reveal, space_orientation,
feature_showcase, texture_detail, light_moment, transition_bridge,
energy_accent, breather, amenity_proof, closing_hero, unknown.

Return only valid JSON. Use null when unknown, [] when empty. Timestamps are
seconds. Confidence is 0 to 1. Do not invent rooms, amenities, people, camera
moves, or transitions that are not visible.

Return:
{
  "schema": "span_graph_analysis.v1",
  "video_summary": {
    "overall_description": "string",
    "estimated_duration_seconds": 0,
    "dominant_style": ["string"],
    "pacing_summary": "string",
    "editing_summary": "string",
    "camera_summary": "string",
    "lighting_color_summary": "string"
  },
  "span_graph": [
    {
      "id": "string",
      "type": "whole_video|music_phrase|property_section|shot_group|shot|transition|micro_event",
      "timeRange": {"start": 0, "end": 0},
      "parentIds": ["string"],
      "summary": "string",
      "content": {
        "spaceType": "exterior|aerial|entry|living|kitchen|dining|bedroom|bathroom|office|hallway|amenity|detail|unknown",
        "visibleFeatures": ["string"],
        "shotScale": "wide|medium|tight|detail|aerial|unknown",
        "viewpoint": "string|null"
      },
      "style": {
        "stylisticFunction": "string",
        "cameraMotion": "string|null",
        "compositionIntent": "string|null",
        "lightingMotion": "string|null",
        "visualTreatment": "string|null",
        "transitionIn": "string|null",
        "transitionOut": "string|null",
        "energyLevel": "low|medium|high|unknown"
      },
      "transferability": "style_invariant|adaptable_content|reference_specific",
      "confidence": 0,
      "notes": "string|null"
    }
  ],
  "important_boundaries": [
    {
      "timestamp": 0,
      "boundaryType": "cut|music_change|section_change|transition|motion_peak|unknown",
      "description": "string",
      "confidence": 0
    }
  ],
  "uncertainties": ["string"]
}
""".strip()


SEGMENT_STYLE_PROMPT = """
You are analyzing one selected span from a finished real estate reference video.
Convert this span into a reusable StyleTemplate fragment for generating the same
style on a different property.

Do not give a normal description. Extract reusable creative structure: purpose
in the edit, content target, camera motion, composition, lighting, color,
pacing, transition behavior, beat sync, substitutions, prompts, and quality
risks.

Do not invent unseen rooms, amenities, objects, camera moves, or transitions.
Use null if unknown and [] if empty. Timestamps are seconds. Confidence is 0-1.
Return only valid JSON.

Important: the reference may use unconventional creative edits such as apparent
weather/season changes, furniture or staging changes while staying in the same
room, whip/zoom/speed-ramp transitions, impossible angle bridges, match cuts,
and music-synced state changes. Capture those as loose creativeEvents objects
with rich natural-language descriptions; do not force them into narrow enums.

Input:
SPAN_ID={{span_id}}
SPAN_TYPE={{span_type}}
SPAN_TIME_RANGE={{span_start}} to {{span_end}}
PARENT_CONTEXT={{parent_context_summary}}
FULL_VIDEO_STYLE={{full_video_style_summary}}

Stylistic functions: establishing_hero, arrival, property_reveal,
space_orientation, feature_showcase, texture_detail, light_moment,
transition_bridge, energy_accent, breather, amenity_proof, closing_hero,
unknown. Transferability: style_invariant, adaptable_content, reference_specific.

Return:
{
  "schema": "style_template_segment.v1",
  "id": "style_template_fragment_for_{{span_id}}",
  "version": "0.1",
  "globalStyle": {
    "mood": ["string"],
    "pacing": "string|null",
    "cameraGrammar": ["string"],
    "lightingDoctrine": ["string"],
    "colorDoctrine": ["string"],
    "editingGrammar": ["string"],
    "negativeConstraints": ["string"]
  },
  "audioPlan": {
    "observedMusicRole": "string|null",
    "beatSyncStrategy": "string|null",
    "requiredCutAnchors": [{"timestamp": 0, "reason": "string", "confidence": 0}]
  },
  "shotSlots": [{
    "id": "string",
    "timeRange": {"start": 0, "end": 0, "duration": 0},
    "stylisticFunction": "string",
    "contentTarget": {
      "spaceType": "exterior|aerial|entry|living|kitchen|dining|bedroom|bathroom|office|hallway|amenity|detail|unknown",
      "featureTags": ["string"],
      "transferability": "style_invariant|adaptable_content|reference_specific",
      "substitutionNotes": "string|null"
    },
    "compositionIntent": {
      "shotScale": "wide|medium|tight|detail|aerial|unknown",
      "viewpoint": "string|null",
      "framing": "string|null",
      "lensFeel": "string|null"
    },
    "cameraMotion": {
      "movementType": "dolly_in|dolly_out|truck_left|truck_right|pan|tilt|crane|orbit|push_in|pull_out|static|drone|unknown",
      "direction": "string|null",
      "speed": "slow|medium|fast|variable|unknown",
      "pathShape": "linear|arc|orbit|top_down|unknown|null"
    },
    "lightingMotion": {"type": "none|shadow_shift|light_sweep|timelapse|window_pull|unknown", "notes": "string|null"},
    "visualTreatment": {"color": "string|null", "contrast": "string|null", "whiteBalance": "string|null", "shadowStrategy": "string|null"},
    "transitionOut": {"type": "cut|whip|flash|match_cut|crossfade|speed_ramp|none|unknown", "notes": "string|null"},
    "promptPlan": {
      "imageEditPrompt": "string|null",
      "videoPrompt": "string",
      "negativePrompt": "string",
      "modelSpecificPrompt": "string|null"
    },
    "creativeEvents": [{
      "kind": "visual_transform|transition_execution|music_sync|camera_bridge|other",
      "tags": ["string"],
      "description": "rich natural language",
      "referenceEvidence": "what is visibly happening in this span",
      "timing": "where it happens within this span",
      "executionHint": {"preferredStrategy": "string", "notes": "string"}
    }],
    "fallbacks": [{"ifMissing": "string", "substituteWith": ["string"], "preserve": "stylistic_function|motion|composition|transition|content"}],
    "qualityChecks": ["string"],
    "confidence": 0
  }],
  "substitutionPolicy": [{"missingReferenceContent": "string", "preserve": "string", "substituteWith": ["string"], "notes": "string"}],
  "promptFragments": [{"id": "string", "appliesTo": ["string"], "text": "string", "transferability": "string"}],
  "qualityPolicy": {
    "mustPreserve": ["architecture", "layout", "permanent fixtures", "room identity"],
    "rejectIf": ["warped walls", "changed windows", "invented amenities", "furniture morphing", "fake signage", "blur"]
  },
  "uncertainties": ["string"]
}
""".strip()
