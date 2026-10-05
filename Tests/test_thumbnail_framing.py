import importlib.util
from pathlib import Path
import unittest

from PIL import Image

spec = importlib.util.spec_from_file_location("framing", Path(__file__).resolve().parents[1] / "Scripts/BBBThumbnailFraming.py")
framing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(framing)


class ThumbnailFramingTests(unittest.TestCase):
    """/** 验证透明取景与失败边界 */"""

    def test_center_and_preserve_aspect(self):
        """/** @return 居中与长宽比断言 */"""
        image = Image.new("RGBA", (512, 512))
        image.paste((120, 90, 60, 255), (200, 100, 300, 300))
        output, bounds = framing.frame_alpha_image(image)
        self.assertEqual(bounds, (200, 100, 300, 300))
        self.assertEqual(output.size, (512, 512))
        alpha_bounds = output.getchannel("A").getbbox()
        self.assertEqual(alpha_bounds[2] - alpha_bounds[0], 220)
        self.assertEqual(alpha_bounds[3] - alpha_bounds[1], 440)

    def test_reject_empty_opaque_and_invalid_size(self):
        """/** @return 无效源图与占幅拒绝断言 */"""
        for image in (Image.new("RGBA", (32, 32)), Image.new("RGBA", (32, 32), (1, 2, 3, 255))):
            with self.assertRaises(ValueError):
                framing.frame_alpha_image(image)
        with self.assertRaises(ValueError):
            framing.frame_alpha_image(Image.new("RGBA", (32, 32)), occupancy=float("nan"))


if __name__ == "__main__":
    unittest.main()
