"""Optional vision inspection through an OpenAI-compatible endpoint.

The core has no vision model and no required dependency. Operators can point
this module at a local or hosted multimodal endpoint. Images are sent as data
URLs, so the configured endpoint receives the pixels; nothing is sent unless a
tool explicitly asks for inspection.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from typing import Any

MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_PROMPT = (
    "Describe what is visibly in this image in two or three sentences. Then say "
    "whether it plausibly matches the requested subject. Do not guess details "
    "that are not visible."
)


class VisionError(Exception):
    pass


def _config() -> tuple[str, str, str, float]:
    base = os.environ.get("REVERSEAI_VISION_URL", "").strip().rstrip("/")
    model = os.environ.get("REVERSEAI_VISION_MODEL", "").strip()
    key = (os.environ.get("REVERSEAI_VISION_API_KEY")
           or os.environ.get("OPENAI_API_KEY") or "").strip()
    try:
        timeout = float(os.environ.get("REVERSEAI_VISION_TIMEOUT", "60") or 60)
    except ValueError:
        timeout = 60.0
    return base, model, key, timeout


def available() -> bool:
    base, model, _key, _timeout = _config()
    return bool(base and model)


def describe_image(data: bytes, mime: str, prompt: str | None = None) -> dict[str, Any]:
    if not data:
        raise VisionError("image is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise VisionError("image exceeds the 8 MiB vision limit")
    base, model, key, timeout = _config()
    if not base or not model:
        raise VisionError(
            "vision is not configured. Set REVERSEAI_VISION_URL and "
            "REVERSEAI_VISION_MODEL (optionally REVERSEAI_VISION_API_KEY).")
    mime = (mime or "image/png").split(";", 1)[0]
    if not mime.startswith("image/"):
        raise VisionError("source is not an image")
    encoded = base64.b64encode(data).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 500,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt or DEFAULT_PROMPT},
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{encoded}"}},
            ],
        }],
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(2_000_000)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise VisionError(f"vision endpoint returned HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VisionError(f"vision request failed: {exc}") from exc
    try:
        body = json.loads(raw.decode("utf-8", "replace"))
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise VisionError("vision endpoint returned an unexpected response") from exc
    if isinstance(content, list):
        content = " ".join(str(part.get("text", "")) for part in content
                           if isinstance(part, dict))
    text = str(content or "").strip()
    if not text:
        raise VisionError("vision endpoint returned no description")
    return {"text": text[:8000], "model": model, "bytes": len(data), "mime": mime}
