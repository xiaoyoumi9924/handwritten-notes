#!/usr/bin/env python3
"""Generate a new handwriting style with SDT style references.

This runs the pretrained SDT model on the supplied style crops. The output
trajectories are model predictions; source crops are never used as output
glyphs. Generated ``.npy`` files use the format consumed by the app's
``SdtTrajectoryStore``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SDT_ROOT = PROJECT_ROOT / "references" / "SDT"
STYLE_DIR_DEFAULT = PROJECT_ROOT / "training/new_chinese_handwriting/prepared/sdt-style-samples"
CHECKPOINT_DEFAULT = PROJECT_ROOT / "training/new_chinese_handwriting/checkpoints/checkpoint-iter199999.pth"
CONTENT_DATA_DEFAULT = PROJECT_ROOT / "training/new_chinese_handwriting/prepared/sdt_inputs/CASIA_CHINESE"
OUTPUT_DEFAULT = PROJECT_ROOT / "training/new_chinese_handwriting/generated/sdt-style"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=CHECKPOINT_DEFAULT)
    parser.add_argument("--style-dir", type=Path, default=STYLE_DIR_DEFAULT)
    parser.add_argument("--content-data-dir", type=Path, default=CONTENT_DATA_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DEFAULT)
    parser.add_argument("--characters", help="comma-separated pilot characters; defaults to the SDT CJK set")
    parser.add_argument("--limit", type=int, help="generate only the first N characters in the selected set")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--max-len", type=int, default=120)
    parser.add_argument("--device", choices=("auto", "mps", "cpu", "cuda"), default="auto")
    parser.add_argument("--seed", type=int, default=20261106)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def load_content_data(data_dir: Path) -> tuple[list[str], dict[str, np.ndarray]]:
    with (data_dir / "character_dict.pkl").open("rb") as stream:
        char_dict = pickle.load(stream)
    with (data_dir / "Chinese_content.pkl").open("rb") as stream:
        content = pickle.load(stream)
    chars = list(char_dict)
    if len(chars) != 6763 or not isinstance(content, dict):
        raise ValueError("Unexpected SDT Chinese content dictionary format")
    missing = [char for char in chars if char not in content]
    if missing:
        raise ValueError(f"Chinese_content.pkl is missing {len(missing)} character images")
    normalized = {char: np.asarray(content[char], dtype=np.float32) / 255.0 for char in chars}
    return chars, normalized


def load_style_images(style_dir: Path) -> tuple[np.ndarray, list[dict[str, object]]]:
    manifest_path = style_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    # Exclude style_reference_contact_sheet.png: it is a QA artifact, not a
    # handwriting sample. The official loader consumes every image in the
    # directory, so keep the file selection explicit.
    files = sorted(style_dir.glob("style_[0-9][0-9].png"))
    if len(files) < 15:
        raise ValueError(f"SDT expects at least 15 style images; found {len(files)} in {style_dir}")
    images = []
    for path in files:
        image = Image.open(path).convert("L").resize((64, 64), Image.Resampling.LANCZOS)
        images.append(np.asarray(image, dtype=np.float32) / 255.0)
    # The official UserDataset loads every image in style_path; do not truncate
    # curated 30-50-character reference sets to the minimum of 15.
    return np.stack(images, axis=0), manifest.get("samples", [])


def choose_device(torch, requested: str):
    if requested == "auto":
        if torch.cuda.is_available():
            requested = "cuda"
        elif torch.backends.mps.is_available():
            requested = "mps"
        else:
            requested = "cpu"
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS was requested but is unavailable in this PyTorch/macOS environment")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is unavailable")
    return torch.device(requested)


def load_model(torch, device, checkpoint: Path):
    if not (SDT_ROOT / "models" / "model.py").is_file():
        raise FileNotFoundError("SDT source not found. Clone https://github.com/dailenson/SDT into references/SDT first.")
    sys.path.insert(0, str(SDT_ROOT))
    import torchvision.models as vision_models
    import models.model as sdt_model

    # The SDT checkpoint includes the ResNet encoder parameters. Avoid an
    # unrelated ImageNet-weight download while creating the architecture.
    original_resnet18 = vision_models.resnet18

    def resnet18_from_checkpoint(*args, **kwargs):
        return original_resnet18(weights=None)

    vision_models.resnet18 = resnet18_from_checkpoint
    sdt_model.models.resnet18 = resnet18_from_checkpoint
    try:
        model = sdt_model.SDT_Generator(
            num_encoder_layers=2,
            num_head_layers=1,
            wri_dec_layers=2,
            gly_dec_layers=2,
        )
    finally:
        vision_models.resnet18 = original_resnet18
        sdt_model.models.resnet18 = original_resnet18

    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    if isinstance(state, dict) and "state_dict" in state and isinstance(state["state_dict"], dict):
        state = state["state_dict"]
    if state and all(key.startswith("module.") for key in state):
        state = {key.removeprefix("module."): value for key, value in state.items()}
    model.load_state_dict(state, strict=True)
    model.to(device)
    model.eval()
    return model


def batches(items: list[str], size: int) -> Iterable[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def make_contact_sheets(image_paths: list[Path], output_dir: Path) -> list[str]:
    if not image_paths:
        return []
    thumb = 128
    columns = 8
    per_sheet = 256
    names = []
    for sheet_index, start in enumerate(range(0, len(image_paths), per_sheet), start=1):
        page = image_paths[start : start + per_sheet]
        rows = (len(page) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * thumb, rows * (thumb + 28)), "#f3efe6")
        draw = ImageDraw.Draw(sheet)
        label_font = ImageFont.load_default()
        for index, path in enumerate(page):
            with Image.open(path) as image:
                image = image.convert("L").resize((thumb, thumb), Image.Resampling.LANCZOS)
            x = (index % columns) * thumb
            y = (index // columns) * (thumb + 28)
            sheet.paste(Image.merge("RGB", (image, image, image)), (x, y))
            draw.text((x + 4, y + thumb + 4), path.stem, fill="#222", font=label_font)
        name = f"preview_contact_sheet_{sheet_index:03d}.png"
        sheet.save(output_dir / name)
        names.append(name)
    return names


def main() -> int:
    args = parse_args()
    for path, label in ((args.checkpoint, "checkpoint"), (args.style_dir, "style directory"),
                        (args.content_data_dir / "character_dict.pkl", "character dictionary"),
                        (args.content_data_dir / "Chinese_content.pkl", "Chinese content dictionary")):
        if not path.exists():
            raise FileNotFoundError(f"Missing {label}: {path}")
    if not SDT_ROOT.is_dir():
        raise FileNotFoundError(f"Missing SDT source checkout: {SDT_ROOT}")

    import torch

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    device = choose_device(torch, args.device)
    style_images, style_manifest_samples = load_style_images(args.style_dir)
    chars, content_images = load_content_data(args.content_data_dir)
    if args.characters:
        selected = list(dict.fromkeys(char for char in args.characters if not char.isspace() and char != ","))
        missing = sorted(set(selected) - set(chars))
        if missing:
            raise ValueError(f"Characters absent from the SDT Chinese set: {''.join(missing)}")
        chars = selected
    if args.limit is not None:
        chars = chars[: max(0, args.limit)]
    if not chars:
        raise ValueError("No target characters selected")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    coordinates_dir = args.output_dir / "coords"
    previews_dir = args.output_dir / "previews"
    coordinates_dir.mkdir(exist_ok=True)
    previews_dir.mkdir(exist_ok=True)
    model = load_model(torch, device, args.checkpoint)

    from utils.util import coords_render

    style_tensor = torch.from_numpy(style_images).unsqueeze(0).unsqueeze(2)
    generated: list[str] = []
    errors: list[dict[str, str]] = []
    for batch_index, char_batch in enumerate(batches(chars, max(1, args.batch_size)), start=1):
        content_tensor = torch.from_numpy(np.stack([content_images[char] for char in char_batch]))
        content_tensor = content_tensor.unsqueeze(1).to(device)
        repeated_style = style_tensor.expand(len(char_batch), -1, -1, -1, -1).to(device)
        with torch.inference_mode():
            predictions = model.inference(repeated_style, content_tensor, args.max_len)
        predictions = predictions.detach().to("cpu").numpy()
        sos = np.tile(np.asarray([[0, 0, 1, 0, 0]], dtype=np.float32), (1, 1))
        for char, prediction in zip(char_batch, predictions):
            trajectory = np.concatenate((sos, prediction.astype(np.float32, copy=False)), axis=0)
            # Keep the first predicted end-of-character token and trim later autoregressive padding.
            end_positions = np.flatnonzero(trajectory[:, 4] >= 0.5)
            if len(end_positions):
                trajectory = trajectory[: int(end_positions[0]) + 1]
            codepoint = f"{ord(char):04x}"
            np.save(coordinates_dir / f"{codepoint}.npy", trajectory, allow_pickle=False)
            try:
                preview = coords_render(trajectory.copy(), split=True, width=256, height=256,
                                        thickness=8, board=1)
                preview.save(previews_dir / f"{codepoint}.png")
            except Exception as error:  # retain predictions so a bad render is reviewable
                errors.append({"character": char, "error": f"preview: {error}"})
            generated.append(char)
        print(f"batch {batch_index}: {len(generated)}/{len(chars)} characters ({device})", flush=True)

    archive_path = args.output_dir / "sdt_style_trajectories.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(coordinates_dir.glob("*.npy")):
            archive.write(path, arcname=path.name)
    preview_paths = sorted(previews_dir.glob("*.png"))
    contact_sheets = make_contact_sheets(preview_paths, args.output_dir)

    style_manifest = args.style_dir / "manifest.json"
    report = {
        "method": "SDT pretrained Chinese writer-style-conditioned trajectory generation",
        "status": "generated",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "device": str(device),
        "checkpoint": display_path(args.checkpoint),
        "checkpoint_sha256": sha256(args.checkpoint),
        "style_directory": display_path(args.style_dir),
        "style_manifest_sha256": sha256(style_manifest) if style_manifest.is_file() else None,
        "style_reference_count": len(style_images),
        "style_reference_samples": style_manifest_samples,
        "content_data_directory": display_path(args.content_data_dir),
        "content_character_count": len(content_images),
        "content_dict_sha256": sha256(args.content_data_dir / "character_dict.pkl"),
        "content_images_sha256": sha256(args.content_data_dir / "Chinese_content.pkl"),
        "content_data_note": "Official SDT Chinese content glyphs provide character structure; SDT predicts the new writer style from reference images.",
        "generated_count": len(generated),
        "characters": generated,
        "trajectory_archive": archive_path.name,
        "preview_count": len(preview_paths),
        "contact_sheets": contact_sheets,
        "errors": errors,
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(generated)} SDT-generated trajectories to {archive_path}")
    if contact_sheets:
        print(f"Contact sheet: {args.output_dir / contact_sheets[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
