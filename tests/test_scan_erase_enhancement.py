import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
from markdown_to_handwrite.scanner import ScanService, process_scan_image


class SparseDetailTests(unittest.TestCase):
    def test_sparse_confident_annotations_retry_but_weak_print_and_dense_ink_do_not(self):
        from markdown_to_handwrite.handwriting_removal import _needs_sparse_detail_pass
        p = np.zeros((1000, 1000), dtype=np.float32)
        p[100:110, 100:250] = .95
        p[200:210, 100:450] = .4
        self.assertTrue(_needs_sparse_detail_pass(p))
        self.assertFalse(_needs_sparse_detail_pass(p * .2))
        p[300:500, 100:600] = .95
        self.assertFalse(_needs_sparse_detail_pass(p))

    def test_detail_retry_keeps_existing_confident_erasure_and_adds_separate_strokes(self):
        from markdown_to_handwrite.handwriting_removal import remove_handwriting
        rgb = np.full((1100, 1100, 3), 220, dtype=np.uint8)
        rgb[400:410, 400:410] = 20
        rgb[800:810, 400:410] = 20
        full = np.zeros((1100, 1100), dtype=np.float32)
        full[400:415, 400:415] = .95
        full[500:505, 400:700] = .4
        detail = np.zeros_like(full)
        detail[800:810, 400:410] = .95
        with patch('markdown_to_handwrite.handwriting_removal._load_model'), patch('markdown_to_handwrite.handwriting_removal._predict', return_value=full), patch('markdown_to_handwrite.handwriting_removal._detail_probability', return_value=detail) as retry:
            result = remove_handwriting(rgb)
        retry.assert_called_once()
        self.assertGreater(result[405, 405, 0], 200)
        self.assertGreater(result[805, 405, 0], 200)
        self.assertTrue(np.array_equal(result[:100], rgb[:100]))
