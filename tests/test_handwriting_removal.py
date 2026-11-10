import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from markdown_to_handwrite.handwriting_removal import _detail_probability, _long_straight_lines, _needs_detail_pass, available, mask_from_probability, remove_handwriting


class HandwritingRemovalTests(unittest.TestCase):
    def test_protects_long_form_rules_but_not_a_short_stroke(self):
        rgb = np.full((200, 300, 3), 255, dtype=np.uint8)
        rgb[80:82, 20:280] = 0
        rgb[120:130, 150:152] = 0
        protected = _long_straight_lines(rgb)
        self.assertTrue(protected[80, 150])
        self.assertFalse(protected[125, 150])

    @unittest.skipUnless(importlib.util.find_spec("torch"), "optional torch dependency")
    def test_erasure_preserves_form_rule_inside_model_mask(self):
        rgb = np.full((120, 180, 3), 255, dtype=np.uint8)
        rgb[60, 20:160] = 0
        rgb[75:83, 80:82] = 0
        prediction = np.zeros((120, 180), dtype=np.float32)
        prediction[55:90, 15:165] = .95
        with patch("markdown_to_handwrite.handwriting_removal._load_model"), patch("markdown_to_handwrite.handwriting_removal._predict", return_value=prediction):
            result = remove_handwriting(rgb)
        self.assertEqual(result[60, 90, 0], 0)
        self.assertGreater(result[78, 80, 0], 200)

    def test_detail_retry_requires_a_substantial_ambiguous_response(self):
        probability = np.zeros((100, 100), dtype=np.float32)
        probability[:2, :10] = .6
        self.assertTrue(_needs_detail_pass(probability))
        probability[:2, :10] = .05
        self.assertFalse(_needs_detail_pass(probability))
        probability[:2, :10] = .95
        self.assertFalse(_needs_detail_pass(probability))

    def test_detail_retry_maps_each_tile_back_to_its_page_position(self):
        image = np.zeros((900, 1100, 3), dtype=np.uint8)
        image[700:, 700:] = 1
        with patch("markdown_to_handwrite.handwriting_removal._predict", side_effect=lambda model, tile, enlarge: tile[:, :, 0].astype(np.float32)):
            result = _detail_probability(None, image)
        self.assertEqual(result.shape, image.shape[:2])
        self.assertEqual(result[800, 800], 1)
        self.assertEqual(result[600, 600], 0)

    def test_isolated_medium_confidence_blob_is_not_erased(self):
        probability = np.zeros((40, 40), dtype=np.float32)
        probability[5:15, 5:15] = .6
        self.assertFalse(mask_from_probability(probability, (80, 80)).any())

    def test_weak_edges_connected_to_confident_ink_are_kept(self):
        probability = np.zeros((40, 40), dtype=np.float32)
        probability[10:20, 10:20] = .4
        probability[14, 14] = .95
        probability[30:35, 30:35] = .6
        mask = mask_from_probability(probability, (40, 40))
        self.assertTrue(mask[11, 11])
        self.assertFalse(mask[32, 32])

    @unittest.skipUnless(importlib.util.find_spec("torch"), "optional torch dependency")
    def test_erased_stroke_matches_shadowed_paper_and_other_pixels_stay_exact(self):
        import torch
        rgb = np.repeat(np.tile(np.linspace(100, 220, 100).astype(np.uint8), (100, 1))[:, :, None], 3, axis=2)
        rgb[50, 40:60] = 0
        probability = torch.zeros((1, 1, 1024, 1024))
        probability[0, 0, 49:52, 40:60] = .95
        class FakeModel:
            def __call__(self, tensor):
                return [[probability]]
        with patch("markdown_to_handwrite.handwriting_removal._load_model", return_value=FakeModel()):
            result = remove_handwriting(rgb)
        self.assertTrue(np.array_equal(result[:40], rgb[:40]))
        self.assertGreater(result[50, 50, 0], 140)
        self.assertLess(result[50, 50, 0], 190)

    def test_low_confidence_printed_page_is_not_stretched_into_an_erasure(self):
        probability = np.linspace(0, .018, 400).reshape(20, 20).astype(np.float32)
        self.assertFalse(mask_from_probability(probability, (100, 100)).any())

    def test_confident_stroke_is_mapped_to_original_resolution(self):
        probability = np.zeros((20, 20), dtype=np.float32)
        probability[10, 10] = .9
        mask = mask_from_probability(probability, (100, 100))
        self.assertEqual(mask.shape, (100, 100))
        self.assertTrue(mask[50, 50])
        self.assertFalse(mask[0, 0])
        self.assertLess(mask.mean(), .1)

    def test_absent_model_reports_unavailable_and_explicit_error(self):
        from markdown_to_handwrite.handwriting_removal import _load_model
        with tempfile.TemporaryDirectory() as folder, patch("markdown_to_handwrite.handwriting_removal.MODEL_PATH", Path(folder) / "missing.pth"):
            _load_model.cache_clear()
            self.assertFalse(available())
            with self.assertRaisesRegex(ValueError, "未安装"):
                remove_handwriting(np.zeros((30, 30, 3), dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
