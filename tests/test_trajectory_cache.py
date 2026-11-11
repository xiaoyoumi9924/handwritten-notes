import unittest
from unittest.mock import patch

import numpy as np

from markdown_to_handwrite.sdt_renderer import TrajectoryStyle, _fit_strokes, _resample_stroke, render_strokes


class TrajectoryCacheTests(unittest.TestCase):
    def test_cached_geometry_preserves_pixels_and_random_variation(self):
        strokes = (np.array([[0, 0], [5, 20], [20, 24]], dtype=np.float32),
                   np.array([[3, 12], [18, 8]], dtype=np.float64))
        style = TrajectoryStyle()

        def uncached(values, width, height, spacing):
            return tuple(_resample_stroke(stroke, spacing) for stroke in _fit_strokes(values, width, height, 0.045))

        images = []
        for seed in (123, 456):
            with patch("markdown_to_handwrite.sdt_renderer._cached_fitted_strokes", side_effect=uncached):
                expected = render_strokes(strokes, 40, 48, 3, (0, 0, 0, 255), np.random.default_rng(seed), style)
            actual = render_strokes(strokes, 40, 48, 3, (0, 0, 0, 255), np.random.default_rng(seed), style)
            self.assertEqual(actual.tobytes(), expected.tobytes())
            images.append(actual.tobytes())
        self.assertNotEqual(images[0], images[1])


if __name__ == "__main__":
    unittest.main()
