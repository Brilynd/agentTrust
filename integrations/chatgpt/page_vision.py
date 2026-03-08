"""
Vision Model for Page Understanding
====================================
Uses GPT-4o's vision capability to analyse browser screenshots,
giving the agent a *visual* understanding of the page in addition
to the DOM-extracted text/elements.

Key features:
  - Automatic screenshot analysis with structured output
  - Configurable triggers (navigation, failures, on-demand)
  - Per-URL caching to avoid redundant API calls
  - Image down-scaling to keep token cost low
  - Environment-variable gate (AGENTTRUST_VISION=false to disable)

Usage:
    from page_vision import PageVision
    vision = PageVision(openai_client)
    analysis = vision.analyse_screenshot(base64_png, url=current_url)
"""

from __future__ import annotations

import base64
import io
import json
import os
import time
from typing import Any, Dict, Optional

# PIL is optional — if unavailable we skip image resizing
try:
    from PIL import Image

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_MODEL = "gpt-4o"
_MAX_IMAGE_WIDTH = 1024          # Resize wider screenshots
_MAX_IMAGE_HEIGHT = 768
_CACHE_TTL_S = 30                # Re-use a cached analysis for this long
_DETAIL_LEVEL = "low"            # "low" | "high" | "auto" — low is cheapest


# ---------------------------------------------------------------------------
# Analysis prompts
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """\
You are a vision-based page analyser for a browser automation agent.
Given a screenshot of a web page, provide a concise structured analysis
that helps the agent decide what to do next.

Respond in **valid JSON** with EXACTLY these keys:
{
  "page_type": "<login|dashboard|search|article|form|error|captcha|modal|other>",
  "summary": "<1-2 sentence description of what is visible>",
  "interactive_elements": [
    {"type": "button|link|input|dropdown|checkbox|tab", "label": "<visible text>", "location": "<top|center|bottom|left|right>"}
  ],
  "blockers": "<description of any modal/overlay/popup/captcha blocking interaction, or null>",
  "errors": "<any visible error messages or warnings, or null>",
  "form_state": "<description of any form fields and their current fill state, or null>",
  "suggestions": "<1-2 short recommendations for the agent's next action>"
}

RULES:
- List at most 10 interactive_elements — prioritise the most prominent ones.
- For interactive_elements label, use the exact visible text on the element.
- Be concise. No preamble, no markdown fences. Only JSON.
"""

TARGETED_ANALYSIS_PROMPT = """\
You are a vision-based page analyser. The browser automation agent is
asking a specific question about the current page screenshot.

QUESTION: {question}

Answer concisely in plain text (not JSON). Focus only on what is asked.
"""


class PageVision:
    """Screenshot analysis powered by GPT-4o vision."""

    def __init__(
        self,
        openai_client: Any,
        model: Optional[str] = None,
        enabled: Optional[bool] = None,
        detail: str = _DETAIL_LEVEL,
        cache_ttl: float = _CACHE_TTL_S,
        max_width: int = _MAX_IMAGE_WIDTH,
        max_height: int = _MAX_IMAGE_HEIGHT,
    ):
        """
        Args:
            openai_client: An ``openai.OpenAI`` instance.
            model: Vision-capable model name (default: gpt-4o).
            enabled: Override enable/disable. ``None`` → read AGENTTRUST_VISION env.
            detail: Image detail level for the API ("low", "high", "auto").
            cache_ttl: Seconds to cache an analysis for the same URL.
            max_width: Maximum image width in pixels before down-scaling.
            max_height: Maximum image height in pixels before down-scaling.
        """
        self._client = openai_client
        self._model = model or os.getenv("OPENAI_VISION_MODEL", _DEFAULT_MODEL)
        self._detail = detail
        self._cache_ttl = cache_ttl
        self._max_w = max_width
        self._max_h = max_height

        # Enable gate
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = os.getenv("AGENTTRUST_VISION", "true").lower() != "false"

        # Simple per-URL cache: { url: (timestamp, analysis_dict) }
        self._cache: Dict[str, tuple] = {}

    # ------------------------------------------------------------------ #
    #  Public API                                                         #
    # ------------------------------------------------------------------ #

    def analyse_screenshot(
        self,
        screenshot_b64: str,
        *,
        url: str = "",
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Analyse a full-page screenshot and return structured JSON.

        Args:
            screenshot_b64: Base-64 encoded PNG screenshot.
            url: Current page URL (used for caching).
            force: Skip cache.

        Returns:
            Parsed analysis dict, or ``None`` if vision is disabled/fails.
        """
        if not self.enabled or not screenshot_b64:
            return None

        # Cache check
        if not force and url and url in self._cache:
            ts, cached = self._cache[url]
            if time.time() - ts < self._cache_ttl:
                return cached

        # Optionally resize
        img_b64 = self._resize_if_needed(screenshot_b64)

        # Call GPT-4o with the image
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}",
                                    "detail": self._detail,
                                },
                            },
                            {
                                "type": "text",
                                "text": f"Current URL: {url}" if url else "Analyse this page.",
                            },
                        ],
                    },
                ],
                max_tokens=800,
                temperature=0.1,
            )

            raw = response.choices[0].message.content or ""
            analysis = self._parse_json(raw)

            # Cache
            if url:
                self._cache[url] = (time.time(), analysis)

            return analysis

        except Exception as e:
            print(f"⚠️  Vision analysis failed: {e}")
            return None

    def ask_about_page(
        self,
        screenshot_b64: str,
        question: str,
        *,
        url: str = "",
    ) -> Optional[str]:
        """
        Ask a targeted question about the current screenshot.

        Returns:
            Plain-text answer, or ``None`` on failure.
        """
        if not self.enabled or not screenshot_b64:
            return None

        img_b64 = self._resize_if_needed(screenshot_b64)

        try:
            response = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": TARGETED_ANALYSIS_PROMPT.format(question=question),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}",
                                    "detail": self._detail,
                                },
                            },
                            {
                                "type": "text",
                                "text": f"Current URL: {url}" if url else "",
                            },
                        ],
                    },
                ],
                max_tokens=400,
                temperature=0.1,
            )

            return (response.choices[0].message.content or "").strip()

        except Exception as e:
            print(f"⚠️  Vision Q&A failed: {e}")
            return None

    def should_analyse(
        self,
        *,
        after_navigation: bool = False,
        after_failure: bool = False,
        sparse_text: bool = False,
        explicit_request: bool = False,
        total_actions: int = 0,
    ) -> bool:
        """
        Heuristic to decide whether to run a vision analysis this turn.

        Returns True when:
          - Vision is enabled AND any of the trigger conditions is met.
        """
        if not self.enabled:
            return False

        if explicit_request:
            return True
        if after_failure:
            return True
        if after_navigation:
            return True
        if sparse_text:
            return True
        # Periodic: every 5 mutating actions, do a visual check
        if total_actions > 0 and total_actions % 5 == 0:
            return True

        return False

    def invalidate_cache(self, url: str = "") -> None:
        """Remove cached analysis for a URL, or clear all."""
        if url:
            self._cache.pop(url, None)
        else:
            self._cache.clear()

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _resize_if_needed(self, b64: str) -> str:
        """Down-scale the image if it exceeds max dimensions. Returns b64."""
        if not PIL_AVAILABLE:
            return b64

        try:
            raw = base64.b64decode(b64)
            img = Image.open(io.BytesIO(raw))
            w, h = img.size

            if w <= self._max_w and h <= self._max_h:
                return b64

            ratio = min(self._max_w / w, self._max_h / h)
            new_size = (int(w * ratio), int(h * ratio))
            img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format="PNG", optimize=True)
            return base64.b64encode(buf.getvalue()).decode()

        except Exception:
            return b64  # fall back to original

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        """
        Best-effort JSON parse — strips markdown fences if the model
        wraps its response.
        """
        text = raw.strip()

        # Strip ```json ... ``` wrappers
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Last resort: return as unstructured summary
            return {
                "page_type": "other",
                "summary": text[:500],
                "interactive_elements": [],
                "blockers": None,
                "errors": None,
                "form_state": None,
                "suggestions": None,
            }

    def format_for_prompt(self, analysis: Dict[str, Any]) -> str:
        """
        Convert an analysis dict into a compact string for injection
        into the agent's system/user prompt.
        """
        if not analysis:
            return ""

        parts = [f"[VISION ANALYSIS]"]
        parts.append(f"Page type: {analysis.get('page_type', 'unknown')}")
        parts.append(f"Summary: {analysis.get('summary', 'N/A')}")

        elems = analysis.get("interactive_elements") or []
        if elems:
            parts.append("Key elements:")
            for el in elems[:8]:
                loc = f" ({el['location']})" if el.get("location") else ""
                parts.append(f"  - [{el.get('type', '?')}] {el.get('label', '?')}{loc}")

        blockers = analysis.get("blockers")
        if blockers:
            parts.append(f"⚠️ Blockers: {blockers}")

        errors = analysis.get("errors")
        if errors:
            parts.append(f"❌ Errors: {errors}")

        form_state = analysis.get("form_state")
        if form_state:
            parts.append(f"Form state: {form_state}")

        suggestions = analysis.get("suggestions")
        if suggestions:
            parts.append(f"Suggestion: {suggestions}")

        return "\n".join(parts)
