import hashlib
import json
import zipfile
from pathlib import Path
from unittest.mock import patch

from markdown_to_handwrite.config import load_config
from markdown_to_handwrite.handwriting import HandwritingEngine

ROOT = Path(__file__).resolve().parents[1]


def test_v6_assets_are_complete_and_match_manifest():
    folder = ROOT / 'font_library/personal_v6'
    manifest = json.loads((folder / 'manifest.json').read_text())
    for name in ('trajectories.zip', 'model_trajectories.zip'):
        path = folder / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest['sha256'][f'font_library/personal_v6/{name}']
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None
            assert len([name for name in archive.namelist() if name.endswith('.npy')]) == 6763


def test_v6_digit_one_is_used_for_text_and_math_and_period_is_inked():
    config = load_config(str(ROOT / 'configs/personal_v6_test.json')).handwriting
    engine = HandwritingEngine(config)
    assert config.handwritten_digit_one and config.handwritten_punctuation
    with patch('markdown_to_handwrite.handwriting.render_strokes', wraps=__import__('markdown_to_handwrite.handwriting', fromlist=['render_strokes']).render_strokes) as render:
        for math in (False, True):
            image = engine._render_with_trajectories('1', 80, 400, 42, math=math)
            assert image.getchannel('A').getbbox()
            assert any(len(call.args[0][0]) == 6 for call in render.call_args_list)
            render.reset_mock()
        engine._render_with_trajectories('。', 80, 400, 42)
        assert any(call.args[3] > engine.uniform_pen_width_px() for call in render.call_args_list)
