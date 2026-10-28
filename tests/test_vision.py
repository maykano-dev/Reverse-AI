"""Optional vision inspection and honest failure when it is not configured."""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reverseai.agent.builtins import InspectImageTool  # noqa: E402
from reverseai.agent.tools import ToolContext  # noqa: E402
from reverseai.vision import VisionError, describe_image  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class VisionTests(unittest.TestCase):
    def test_unconfigured_vision_fails_honestly(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ("REVERSEAI_VISION_URL", "REVERSEAI_VISION_MODEL",
                        "REVERSEAI_VISION_API_KEY", "OPENAI_API_KEY"):
                os.environ.pop(key, None)
            with self.assertRaises(VisionError) as ctx:
                describe_image(PNG, "image/png")
        self.assertIn("not configured", str(ctx.exception))

    def test_describe_posts_a_data_url_to_the_configured_endpoint(self):
        payload = {"choices": [{"message": {"content": "A container terminal."}}]}
        response = _Resp(json.dumps(payload).encode())
        env = {"REVERSEAI_VISION_URL": "https://vision.example/v1",
               "REVERSEAI_VISION_MODEL": "vision-small"}
        with patch.dict(os.environ, env, clear=False), \
             patch("reverseai.vision.urllib.request.urlopen",
                   return_value=response) as call:
            result = describe_image(PNG, "image/png", "Is this a port?")
        self.assertIn("container terminal", result["text"])
        request = call.call_args.args[0]
        body = json.loads(request.data.decode())
        image = body["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(image.startswith("data:image/png;base64,"))

    def test_tool_uses_the_configured_inspector(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "port.png"
            path.write_bytes(PNG)
            ctx = ToolContext(job_id="v", workspace=td,
                              extra={"project_dir": td})
            with patch("reverseai.vision.describe_image",
                       return_value={"text": "A crane and containers.",
                                     "model": "vision-small",
                                     "bytes": len(PNG), "mime": "image/png"}):
                result = InspectImageTool().run({"source": str(path)}, ctx)
        self.assertTrue(result.ok, result.content)
        self.assertIn("crane", result.data["description"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
