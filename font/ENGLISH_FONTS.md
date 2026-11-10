# English handwriting fonts

The two optional Latin handwriting fonts in this directory are distributed under the SIL Open Font License 1.1. Their full license texts are included beside the font files.

| File | Family | Source |
|---|---|---|
| `Latin-Caveat-Regular.ttf` | Caveat Regular | [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/caveat/METADATA.pb); original project source at the commit recorded in that metadata |
| `Latin-Kalam-Regular.ttf` | Kalam Regular | [Google Fonts metadata](https://github.com/google/fonts/blob/main/ofl/kalam/METADATA.pb) |

Choose either file in the WebUI's English font field or set `handwriting.latin_font_path` in a JSON config. These fonts affect Latin letters, digits, and ASCII punctuation in text rendering; Chinese glyphs continue to use their existing path, and math expressions continue to use the math font.
