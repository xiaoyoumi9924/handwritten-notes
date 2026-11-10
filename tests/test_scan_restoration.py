import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from markdown_to_handwrite.scanner import ScanService
from markdown_to_handwrite.scan_restoration import normalize_scan_edits, restore_regions, draw_scan_marks


class ScanRestorationTests(unittest.TestCase):
    @unittest.skipUnless(Path('/System/Library/Fonts/Supplemental/Songti.ttc').is_file(), 'macOS Songti font required')
    def test_scan_comment_uses_regular_song_type_in_export(self):
        image = Image.new('RGB', (500, 300), 'white')
        comment = {'kind': 'comment', 'text': '宋体批注', 'color': '#183865', 'width': .04, 'points': [[.1,.1]]}
        with patch('markdown_to_handwrite.scan_restoration.ImageFont.truetype', wraps=ImageFont.truetype) as load:
            result = draw_scan_marks(image, [comment])
        self.assertEqual(load.call_args.kwargs['index'], 4)
        self.assertTrue(np.any(np.asarray(result) != 255))

    def test_rejects_out_of_bounds_nonfinite_and_excessive_regions(self):
        invalid = [[0, 0, 2, .2], [0, 0, float("nan"), .2], [True, 0, .2, .2], [.2, .2, 0, .2]]
        for rect in invalid:
            with self.subTest(rect=rect), self.assertRaises(ValueError):
                normalize_scan_edits([{"marks": [{"kind": "restore", "rect": rect}]}], 1)
        with self.assertRaises(ValueError):
            normalize_scan_edits([{"marks": [{"kind": "restore", "rect": [0,0,.2,.2]}]*151}], 1)

    def test_only_selected_pixels_are_restored(self):
        processed = Image.new("RGB", (100, 100), "white")
        original = Image.new("RGB", (100, 100), (20, 40, 70))
        result = restore_regions(processed, original, [[.2, .3, .4, .2]])
        self.assertEqual(result.getpixel((30, 40)), (20, 40, 70))
        self.assertEqual(result.getpixel((10, 10)), (255, 255, 255))
        with self.assertRaises(ValueError):
            restore_regions(processed, original.resize((50, 50)), [[0,0,.5,.5]])

    def test_preview_export_alignment_undo_and_filter_switch(self):
        image = Image.new("RGB", (160, 120), (180, 210, 230))
        ImageDraw.Draw(image).rectangle((20, 20, 80, 50), fill="black")
        stream = io.BytesIO()
        image.save(stream, "PNG")
        with tempfile.TemporaryDirectory() as folder:
            service = ScanService(Path(folder))
            scan_id = service.upload("exam.png", stream.getvalue())["scanId"]
            root = Path(folder)/scan_id
            metadata = json.loads((root/"scan.json").read_text())
            metadata["corners"] = None
            (root/"scan.json").write_text(json.dumps(metadata))
            # Compatibility for previously saved erasure exports: the retired
            # mode cannot be requested, but old restoration data remains usable.
            response = service.process(scan_id, {"mode": "smart", "rotation": 90, "crop": [.1,.1,.8,.8]})
            (root/"current-options.json").write_text(json.dumps({"mode": "remove_handwriting"}))
            self.assertIn("alignedOriginalUrl", response)
            base_bytes = (root/"current.png").read_bytes()
            with Image.open(root/"current.png") as opened:
                base = opened.convert("RGB")
            with Image.open(root/"aligned-original.png") as opened:
                original = opened.convert("RGB")
            marks = [{"kind": "restore", "rect": [.1,.1,.5,.5]}]
            expected = restore_regions(base, original, [marks[0]["rect"]])
            with patch("markdown_to_handwrite.handwriting_removal.remove_handwriting", side_effect=AssertionError("must not rerun AI")):
                preview = service.restoration_preview(scan_id, marks)
                exported = service.export([scan_id], "png", [{"marks": marks}])
            with Image.open(root/Path(preview["url"]).name) as opened:
                difference = np.abs(np.asarray(opened.convert("RGB")).astype(float)-np.asarray(expected).astype(float))
                self.assertLess(difference.mean(), 4)
            with Image.open(Path(folder)/"exports"/Path(exported["url"]).name) as opened:
                self.assertTrue(np.array_equal(np.asarray(opened), np.asarray(expected)))
            # Undo needs no destructive rewrite of the original or AI result.
            undone = service.export([scan_id], "png", [{"marks": []}])
            self.assertEqual((Path(folder)/"exports"/Path(undone["url"]).name).read_bytes(), base_bytes)
            self.assertEqual((root/"current.png").read_bytes(), base_bytes)
            annotated = service.export([scan_id], "png", [{"marks": marks + [{
                "kind": "underline", "color": "#ff0000", "width": .02,
                "points": [[.1,.2],[.8,.2]],
            }]}])
            with Image.open(Path(folder)/"exports"/Path(annotated["url"]).name) as opened:
                self.assertEqual(opened.getpixel((round(.4*(opened.width-1)), round(.2*(opened.height-1)))), (255,0,0))
            service.process(scan_id, {"mode": "smart"})
            switched_bytes = (root/"current.png").read_bytes()
            switched = service.export([scan_id], "png", [{"marks": marks}])
            self.assertEqual((Path(folder)/"exports"/Path(switched["url"]).name).read_bytes(), switched_bytes)


if __name__ == "__main__":
    unittest.main()
