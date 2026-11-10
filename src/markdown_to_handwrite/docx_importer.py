from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
NS = {"w": W, "m": M}


@dataclass
class DocxImportResult:
    markdown: str
    warnings: list[str]


def import_docx(path: str | Path) -> DocxImportResult:
    return import_docx_bytes(Path(path).read_bytes())


def import_docx_bytes(data: bytes) -> DocxImportResult:
    """Convert a DOCX package into Markdown while retaining paragraph order and OMML math."""
    warnings: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            infos = package.infolist()
            total_size = sum(info.file_size for info in infos)
            if total_size > 32 * 1024 * 1024:
                raise ValueError("DOCX 解压后的内容超过 32 MB，已停止导入。")
            names = set(package.namelist())
            if "word/document.xml" not in names:
                raise ValueError("文件中没有找到 Word 主文档，无法按 DOCX 导入。")
            document = _xml(package.read("word/document.xml"))
            styles = _read_styles(package, names)
            numbering = _read_numbering(package, names)
    except zipfile.BadZipFile as error:
        raise ValueError("文件不是有效的 DOCX 文档。") from error

    body = document.find("w:body", NS)
    if body is None:
        raise ValueError("DOCX 中没有找到文档正文。")

    blocks: list[str] = []
    list_key: tuple[str, str, int] | None = None
    list_lines: list[str] = []

    def flush_list() -> None:
        nonlocal list_key, list_lines
        if list_lines:
            blocks.append("\n".join(list_lines))
        list_key, list_lines = None, []

    for child in body:
        if child.tag == f"{{{W}}}p":
            paragraph = _paragraph_to_markdown(child, styles, numbering, warnings)
            if paragraph is None:
                flush_list()
                continue
            text, heading_level, list_info = paragraph
            if list_info is not None:
                num_id, level, ordered, start = list_info
                key = (num_id, "ordered" if ordered else "bullet", level)
                if list_key != key:
                    flush_list()
                    list_key = key
                marker = f"{start}. " if ordered else "- "
                list_lines.append("  " * level + marker + text)
                continue
            flush_list()
            if heading_level:
                blocks.append(f"{'#' * heading_level} {text}")
            elif text:
                blocks.append(text)
        elif child.tag == f"{{{W}}}tbl":
            flush_list()
            table, table_warnings = _table_to_markdown(child, styles, numbering)
            warnings.extend(table_warnings)
            if table:
                blocks.append(table)
        else:
            flush_list()

    flush_list()
    return DocxImportResult("\n\n".join(block for block in blocks if block.strip()).strip() + "\n", warnings)


def _xml(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as error:
        raise ValueError("DOCX 内的 XML 结构损坏，无法导入。") from error


def _read_styles(package: zipfile.ZipFile, names: set[str]) -> dict[str, int]:
    if "word/styles.xml" not in names:
        return {}
    root = _xml(package.read("word/styles.xml"))
    result: dict[str, int] = {}
    for style in root.findall("w:style", NS):
        style_id = style.get(f"{{{W}}}styleId", "")
        outline = style.find("w:pPr/w:outlineLvl", NS)
        if outline is not None:
            try:
                result[style_id] = min(6, int(outline.get(f"{{{W}}}val", "0")) + 1)
            except ValueError:
                continue
    return result


def _read_numbering(package: zipfile.ZipFile, names: set[str]) -> dict[str, tuple[bool, int, int]]:
    if "word/numbering.xml" not in names:
        return {}
    root = _xml(package.read("word/numbering.xml"))
    abstracts: dict[str, dict[int, tuple[bool, int]]] = {}
    for abstract in root.findall("w:abstractNum", NS):
        abstract_id = abstract.get(f"{{{W}}}abstractNumId", "")
        levels: dict[int, tuple[bool, int]] = {}
        for level in abstract.findall("w:lvl", NS):
            try:
                ilvl = int(level.get(f"{{{W}}}ilvl", "0"))
            except ValueError:
                continue
            fmt = level.find("w:numFmt", NS)
            start = level.find("w:start", NS)
            fmt_value = fmt.get(f"{{{W}}}val", "bullet") if fmt is not None else "bullet"
            start_value = int(start.get(f"{{{W}}}val", "1")) if start is not None else 1
            levels[ilvl] = (fmt_value != "bullet", start_value)
        abstracts[abstract_id] = levels
    result: dict[str, tuple[bool, int, int]] = {}
    for num in root.findall("w:num", NS):
        num_id = num.get(f"{{{W}}}numId", "")
        abstract = num.find("w:abstractNumId", NS)
        abstract_id = abstract.get(f"{{{W}}}val", "") if abstract is not None else ""
        for ilvl, (ordered, start) in abstracts.get(abstract_id, {}).items():
            override = num.find(f"w:lvlOverride[@w:ilvl='{ilvl}']/w:startOverride", NS)
            if override is not None:
                try:
                    start = int(override.get(f"{{{W}}}val", str(start)))
                except ValueError:
                    pass
            result[f"{num_id}:{ilvl}"] = (ordered, ilvl, start)
    return result


def _paragraph_to_markdown(p: ET.Element, styles, numbering, warnings):
    ppr = p.find("w:pPr", NS)
    style = ppr.find("w:pStyle", NS) if ppr is not None else None
    style_id = style.get(f"{{{W}}}val", "") if style is not None else ""
    heading_level = styles.get(style_id, 0)

    num_id = ilvl = None
    num_pr = ppr.find("w:numPr", NS) if ppr is not None else None
    if num_pr is not None:
        num_node = num_pr.find("w:numId", NS)
        lvl_node = num_pr.find("w:ilvl", NS)
        if num_node is not None:
            num_id = num_node.get(f"{{{W}}}val", "")
            try:
                ilvl = int(lvl_node.get(f"{{{W}}}val", "0")) if lvl_node is not None else 0
            except ValueError:
                ilvl = 0

    chunks: list[str] = []
    display_only = True
    for child in p:
        if child.tag == f"{{{M}}}oMathPara":
            formula = _omml(child)
            if formula:
                if formula.startswith(">") and formula.endswith(">"):
                    warnings.append("检测到公式首尾包有 ‘>’；已按源文档保留，请核对是否为多余符号。")
                chunks.append(f"\n\n$$\n{formula}\n$$\n\n")
        elif child.tag == f"{{{M}}}oMath":
            formula = _omml(child)
            if formula:
                if formula.startswith(">") and formula.endswith(">"):
                    warnings.append("检测到公式首尾包有 ‘>’；已按源文档保留，请核对是否为多余符号。")
                chunks.append(f"\\({formula}\\)")
                display_only = False
        elif child.tag == f"{{{W}}}r":
            text, has_break = _run_text(child)
            if has_break:
                chunks.append("<br>")
            elif text:
                chunks.append(_escape_markdown(text))
                if text.strip():
                    display_only = False
        elif child.tag == f"{{{W}}}hyperlink":
            text = "".join((node.text or "") for node in child.findall(".//w:t", NS))
            if text:
                chunks.append(_escape_markdown(text))
                display_only = False
        elif child.tag in {f"{{{W}}}bookmarkStart", f"{{{W}}}bookmarkEnd", f"{{{W}}}pPr"}:
            continue

    text = "".join(chunks).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        return None
    list_info = None
    if num_id is not None:
        ordered, level, start = numbering.get(f"{num_id}:{ilvl}", (False, ilvl or 0, 1))
        list_info = (num_id, level, ordered, start)
    # A paragraph containing only one or more display math objects should remain a display block.
    if display_only and "$$" in text:
        text = text.strip()
    return text, heading_level, list_info


def _run_text(run: ET.Element) -> tuple[str, bool]:
    parts: list[str] = []
    hard_break = False
    for child in run:
        if child.tag == f"{{{W}}}t":
            parts.append(child.text or "")
        elif child.tag == f"{{{W}}}tab":
            parts.append("    ")
        elif child.tag in {f"{{{W}}}br", f"{{{W}}}cr"}:
            hard_break = True
    return "".join(parts), hard_break


def _escape_markdown(text: str) -> str:
    # Preserve ordinary prose while preventing imported table pipes from changing columns.
    return text.replace("|", r"\|")


def _table_to_markdown(table: ET.Element, styles, numbering):
    warnings: list[str] = []
    xml_rows = table.findall("w:tr", NS)
    grid_columns = len(table.findall("w:tblGrid/w:gridCol", NS))
    specs: list[list[tuple[ET.Element, int, int, str | None]]] = []
    for row in xml_rows:
        row_specs: list[tuple[ET.Element, int, int, str | None]] = []
        column = 0
        for cell in row.findall("w:tc", NS):
            grid_span = cell.find("w:tcPr/w:gridSpan", NS)
            try:
                span = max(1, int(grid_span.get(f"{{{W}}}val", "1"))) if grid_span is not None else 1
            except ValueError:
                span = 1
            merge = cell.find("w:tcPr/w:vMerge", NS)
            merge_value = None
            if merge is not None:
                merge_value = "restart" if merge.get(f"{{{W}}}val") == "restart" else "continue"
            row_specs.append((cell, column, span, merge_value))
            column += span
        specs.append(row_specs)

    def cell_text(cell: ET.Element) -> str:
        paras: list[str] = []
        for p in cell.findall("w:p", NS):
            converted = _paragraph_to_markdown(p, styles, numbering, warnings)
            if converted:
                cell_text = converted[0]
                cell_text = re.sub(
                    r"\$\$\s*(.*?)\s*\$\$",
                    lambda match: r"\(" + match.group(1).strip().replace("|", r"\|") + r"\)",
                    cell_text,
                    flags=re.S,
                )
                cell_text = re.sub(
                    r"\\\((.*?)\\\)",
                    lambda match: r"\(" + match.group(1).replace("|", r"\|") + r"\)",
                    cell_text,
                    flags=re.S,
                )
                paras.append(re.sub(r"\s*\n\s*", " ", cell_text))
        return "<br>".join(value for value in paras if value)

    cell_texts = {
        (row_index, column): cell_text(cell)
        for row_index, row_specs in enumerate(specs)
        for cell, column, _span, _merge in row_specs
    }
    rowspans: dict[tuple[int, int], int] = {}
    continuations: set[tuple[int, int]] = set()
    for row_index, row_specs in enumerate(specs):
        for _cell, column, span, merge in row_specs:
            if merge != "restart":
                continue
            row_span = 1
            for next_row in range(row_index + 1, len(specs)):
                next_cell = next((item for item in specs[next_row] if item[1] == column), None)
                if next_cell is None or next_cell[2] != span or next_cell[3] != "continue":
                    break
                continuations.add((next_row, column))
                row_span += 1
            if row_span > 1:
                rowspans[(row_index, column)] = row_span
                anchor_text = cell_texts[(row_index, column)]
                for next_row in range(row_index + 1, row_index + row_span):
                    continued_text = cell_texts.get((next_row, column), "")
                    if continued_text and continued_text not in anchor_text:
                        anchor_text = "<br>".join(part for part in (anchor_text, continued_text) if part)
                cell_texts[(row_index, column)] = anchor_text

    rows: list[list[str]] = []
    merge_warning_added = False
    for row_index, row_specs in enumerate(specs):
        values: list[str] = []
        for cell, column, span, merge in row_specs:
            horizontal_merge = cell.find("w:tcPr/w:hMerge", NS)
            if horizontal_merge is not None and not merge_warning_added:
                warnings.append("检测到旧式横向合并单元格；内容会保留，但合并外观会按普通网格展开。")
                merge_warning_added = True
            is_continuation = (row_index, column) in continuations
            value = cell_texts.get((row_index, column), "")
            if span > 1:
                value = f"<!--docx-colspan={span}-->" + value
            row_span = 0 if is_continuation else rowspans.get((row_index, column), 1)
            if row_span != 1:
                value = f"<!--docx-rowspan={row_span}-->" + value
            values.append(value)
            if span > 1:
                placeholder = "<!--docx-colspan=0-->"
                if is_continuation:
                    placeholder += "<!--docx-rowspan=0-->"
                values.extend([placeholder] * (span - 1))
        rows.append(values)
    if not rows:
        return "", warnings
    columns = max(grid_columns, max(map(len, rows), default=0))
    if not columns:
        return "", warnings
    normalized = [row + [""] * (columns - len(row)) for row in rows]
    lines = ["| " + " | ".join(normalized[0]) + " |", "| " + " | ".join("---" for _ in range(columns)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in normalized[1:])
    return "\n".join(lines), warnings


def _omml(element: ET.Element) -> str:
    """Translate the common Office Math Markup Language structures into supported LaTeX."""
    tag = element.tag.rsplit("}", 1)[-1]
    if tag == "r":
        value = "".join(node.text or "" for node in element.findall("m:t", NS))
        return _math_text(value)
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "fName", "deg", "lim", "arg", "mr", "mc", "eqArr", "m"}:
        return "".join(_omml(child) for child in element if not _is_property(child))
    if tag == "sSub":
        base = _child(element, "e")
        sub = _child(element, "sub")
        return f"{{{_omml(base)}}}_{{{_omml(sub)}}}"
    if tag == "sSup":
        base = _child(element, "e")
        sup = _child(element, "sup")
        return f"{{{_omml(base)}}}^{{{_omml(sup)}}}"
    if tag == "sSubSup":
        base, sub, sup = _child(element, "e"), _child(element, "sub"), _child(element, "sup")
        return f"{{{_omml(base)}}}_{{{_omml(sub)}}}^{{{_omml(sup)}}}"
    if tag == "f":
        return f"\\frac{{{_omml(_child(element, 'num'))}}}{{{_omml(_child(element, 'den'))}}}"
    if tag == "rad":
        radicand = _omml(_child(element, "e"))
        degree = _omml(_child(element, "deg"))
        return f"\\sqrt[{degree}]{{{radicand}}}" if degree.strip() else f"\\sqrt{{{radicand}}}"
    if tag == "d":
        props = _child(element, "dPr")
        begin = _property_value(props, "begChr", "(")
        end = _property_value(props, "endChr", ")")
        sep = _property_value(props, "sepChr", "|")
        body = _omml(_child(element, "e"))
        if len(element.findall("m:e", NS)) > 1:
            body = sep.join(_omml(item) for item in element.findall("m:e", NS))
        return f"{_delimiter(begin)}{body}{_delimiter(end)}"
    if tag == "nary":
        props = _child(element, "naryPr")
        operator = _property_value(props, "chr", "∫")
        op_tex = _operator_tex(operator)
        lower = _omml(_child(element, "sub"))
        upper = _omml(_child(element, "sup"))
        body = _omml(_child(element, "e"))
        result = op_tex
        if lower.strip(): result += f"_{{{lower}}}"
        if upper.strip(): result += f"^{{{upper}}}"
        return result + body
    if tag == "func":
        name = _omml(_child(element, "fName"))
        arg = _omml(_child(element, "e"))
        return f"\\operatorname{{{name}}}\\left({arg}\\right)"
    if tag == "acc":
        body = _omml(_child(element, "e"))
        mark = _property_value(_child(element, "accPr"), "chr", "ˆ")
        command = {"ˆ": "hat", "̂": "hat", "̃": "tilde", "⃗": "vec", "˙": "dot", "¨": "ddot", "¯": "bar"}.get(mark, "hat")
        return f"\\{command}{{{body}}}"
    if tag == "bar":
        body = _omml(_child(element, "e"))
        position = _property_value(_child(element, "barPr"), "pos", "top")
        return f"\\overline{{{body}}}" if position == "top" else f"\\underline{{{body}}}"
    if tag == "groupChr":
        body = _omml(_child(element, "e"))
        mark = _property_value(_child(element, "groupChrPr"), "chr", "⏞")
        return f"\\overbrace{{{body}}}" if mark in {"⏞", "︷"} else f"\\underbrace{{{body}}}"
    if tag in {"limUpp", "limLow"}:
        body, limit = _omml(_child(element, "e")), _omml(_child(element, "lim"))
        return f"\\overset{{{limit}}}{{{body}}}" if tag == "limUpp" else f"\\underset{{{limit}}}{{{body}}}"
    if tag in {"box", "borderBox", "phant"}:
        return _omml(_child(element, "e"))
    if tag == "eqArr":
        rows = [_omml(row) for row in element.findall("m:e", NS)]
        return r"\begin{aligned}" + r" \\ ".join(rows) + r"\end{aligned}"
    if tag == "m":
        rows = []
        for row in element.findall("m:mr", NS):
            rows.append(" & ".join(_omml(cell) for cell in row.findall("m:e", NS)))
        return r"\begin{matrix}" + r" \\ ".join(rows) + r"\end{matrix}"
    if tag == "t":
        return _math_text(element.text or "")
    return "".join(_omml(child) for child in element if not _is_property(child))


def _child(element: ET.Element, name: str) -> ET.Element:
    found = element.find(f"m:{name}", NS)
    return found if found is not None else ET.Element(f"{{{M}}}{name}")


def _is_property(element: ET.Element) -> bool:
    return element.tag.rsplit("}", 1)[-1].endswith("Pr") or element.tag.rsplit("}", 1)[-1] in {"ctrlPr", "rPr"}


def _property_value(props: ET.Element | None, name: str, default: str) -> str:
    if props is None:
        return default
    child = props.find(f"m:{name}", NS)
    return child.get(f"{{{M}}}val", default) if child is not None else default


def _delimiter(value: str) -> str:
    return {"∣": "|", "∥": r"\|", "⌊": r"\lfloor", "⌋": r"\rfloor", "⌈": r"\lceil", "⌉": r"\rceil", "{": r"\{", "}": r"\}"}.get(value, value)


def _operator_tex(value: str) -> str:
    return {"∑": r"\sum", "∏": r"\prod", "∫": r"\int", "∮": r"\oint", "⋃": r"\bigcup", "⋂": r"\bigcap"}.get(value, value)


def _math_text(value: str) -> str:
    if not value:
        return ""
    escaped = _escape_math_literal(value)
    if re.search(r"[\u3400-\u9fff]", value):
        return f"\\text{{{escaped}}}"
    return escaped


def _escape_math_literal(value: str) -> str:
    replacements = {
        "\\": r"\backslash ",
        "{": r"\{",
        "}": r"\}",
        "_": r"\_",
        "^": r"\^",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "$": r"\$",
    }
    return "".join(replacements.get(char, char) for char in value)
