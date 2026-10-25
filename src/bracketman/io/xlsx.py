"""Pure-Python reader and writer for .xlsx (OpenXML) workbooks."""

from __future__ import annotations

import io
from pathlib import Path
from xml.sax.saxutils import escape
import xml.etree.ElementTree as ET
import zipfile


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _col_letters_to_index(col_str: str) -> int:
    """Convert Excel column letters (e.g. 'A' -> 0, 'Z' -> 25, 'AA' -> 26)."""
    idx = 0
    for ch in col_str.upper():
        if "A" <= ch <= "Z":
            idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return max(0, idx - 1)


def _index_to_col_letters(idx: int) -> str:
    """Convert 0-based column index to Excel letters ('A', 'B', ..., 'AA')."""
    letters = []
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        letters.append(chr(ord("A") + rem))
    return "".join(reversed(letters))


def read_xlsx_sheets(source: bytes | str | Path) -> list[tuple[str, list[list[str]]]]:
    """Read an .xlsx file (bytes or path) and return [(sheet_name, rows), ...]."""
    zf_input: io.BytesIO | str | Path = (
        io.BytesIO(source) if isinstance(source, bytes) else source
    )
    ns = {"ns": MAIN_NS, "r": REL_NS}

    with zipfile.ZipFile(zf_input, "r") as z:
        wb_xml = ET.fromstring(z.read("xl/workbook.xml"))

        # Map relationship r:id -> target worksheet path
        rel_map: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in z.namelist():
            rels_xml = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            for rel in rels_xml.findall(f"{{{PKG_REL_NS}}}Relationship"):
                rid = rel.attrib.get("Id", "")
                target = rel.attrib.get("Target", "").lstrip("/")
                if not target.startswith("xl/"):
                    target = f"xl/{target}"
                rel_map[rid] = target

        # Read sharedStrings if present
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_xml = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in ss_xml.findall(".//ns:si", ns):
                texts = [t.text or "" for t in si.findall(".//ns:t", ns)]
                shared_strings.append("".join(texts))

        result: list[tuple[str, list[list[str]]]] = []
        sheet_elems = wb_xml.findall(".//ns:sheet", ns)
        for idx, sheet_el in enumerate(sheet_elems, start=1):
            sheet_name = sheet_el.attrib.get("name", f"Sheet{idx}")
            state = sheet_el.attrib.get("state", "visible")
            if state in ("hidden", "veryHidden"):
                continue

            rid = sheet_el.attrib.get(f"{{{REL_NS}}}id", "")
            ws_path = rel_map.get(rid, f"xl/worksheets/sheet{idx}.xml")
            if ws_path not in z.namelist():
                alt_path = f"xl/worksheets/sheet{idx}.xml"
                if alt_path in z.namelist():
                    ws_path = alt_path
                else:
                    continue

            ws_xml = ET.fromstring(z.read(ws_path))
            rows_data: list[list[str]] = []
            last_row_num = 0

            for row_el in ws_xml.findall(".//ns:sheetData/ns:row", ns):
                rnum_str = row_el.attrib.get("r")
                rnum = int(rnum_str) if rnum_str and rnum_str.isdigit() else (last_row_num + 1)
                while last_row_num + 1 < rnum:
                    rows_data.append([])
                    last_row_num += 1
                last_row_num = rnum

                row_cells: dict[int, str] = {}
                max_col = -1
                for cell_el in row_el.findall("ns:c", ns):
                    coord = cell_el.attrib.get("r", "")
                    col_letters = "".join(ch for ch in coord if ch.isalpha())
                    col_idx = _col_letters_to_index(col_letters) if col_letters else (max_col + 1)
                    max_col = max(max_col, col_idx)

                    cell_type = cell_el.attrib.get("t", "")
                    v_el = cell_el.find("ns:v", ns)
                    is_el = cell_el.find("ns:is", ns)
                    val = ""
                    if v_el is not None and v_el.text is not None:
                        if cell_type == "s":
                            s_idx = int(v_el.text)
                            val = shared_strings[s_idx] if 0 <= s_idx < len(shared_strings) else ""
                        elif cell_type == "b":
                            val = "TRUE" if v_el.text == "1" else "FALSE"
                        else:
                            val = v_el.text
                    elif is_el is not None:
                        val = "".join(t.text or "" for t in is_el.findall(".//ns:t", ns))

                    row_cells[col_idx] = val

                if max_col >= 0:
                    row_list = [row_cells.get(c, "") for c in range(max_col + 1)]
                else:
                    row_list = []
                rows_data.append(row_list)

            result.append((sheet_name, rows_data))

    return result


def write_xlsx_sheets(
    path: str | Path,
    sheets: list[tuple[str, list[list[object]]]],
) -> None:
    """Write a multi-tab .xlsx workbook without requiring external libraries."""
    if not sheets:
        sheets = [("Sheet1", [])]

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml
        overrides = "\n".join(
            f'  <Override PartName="/xl/worksheets/sheet{i}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, len(sheets) + 1)
        )
        content_types = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
{overrides}
</Types>"""
        z.writestr("[Content_Types].xml", content_types)

        # _rels/.rels
        root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""
        z.writestr("_rels/.rels", root_rels)

        # xl/workbook.xml and xl/_rels/workbook.xml.rels
        sheet_tags = []
        rel_tags = []
        used_names: set[str] = set()
        for i, (raw_name, _) in enumerate(sheets, start=1):
            clean_name = "".join(c for c in raw_name if c not in '[]:*?/\\').strip()[:31] or f"Sheet{i}"
            base_name = clean_name
            suffix = 2
            while clean_name.lower() in used_names:
                s_str = f"_{suffix}"
                clean_name = f"{base_name[:31 - len(s_str)]}{s_str}"
                suffix += 1
            used_names.add(clean_name.lower())

            sheet_tags.append(
                f'    <sheet name="{escape(clean_name)}" sheetId="{i}" r:id="rId{i}"/>'
            )
            rel_tags.append(
                f'  <Relationship Id="rId{i}" '
                f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{i}.xml"/>'
            )

        workbook_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">
  <sheets>
{chr(10).join(sheet_tags)}
  </sheets>
</workbook>"""
        z.writestr("xl/workbook.xml", workbook_xml)

        wb_rels_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="{PKG_REL_NS}">
{chr(10).join(rel_tags)}
</Relationships>"""
        z.writestr("xl/_rels/workbook.xml.rels", wb_rels_xml)

        # Worksheets
        for i, (_, rows) in enumerate(sheets, start=1):
            row_xml_parts = []
            for r_idx, row in enumerate(rows, start=1):
                cell_xml_parts = []
                for c_idx, val in enumerate(row):
                    if val is None or val == "":
                        continue
                    coord = f"{_index_to_col_letters(c_idx)}{r_idx}"
                    if isinstance(val, (int, float)) and not isinstance(val, bool):
                        cell_xml_parts.append(f'<c r="{coord}"><v>{val}</v></c>')
                    else:
                        text = escape(str(val))
                        cell_xml_parts.append(
                            f'<c r="{coord}" t="inlineStr"><is><t>{text}</t></is></c>'
                        )
                row_xml_parts.append(f'    <row r="{r_idx}">{"".join(cell_xml_parts)}</row>')

            ws_xml = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{MAIN_NS}">
  <sheetData>
{chr(10).join(row_xml_parts)}
  </sheetData>
</worksheet>"""
            z.writestr(f"xl/worksheets/sheet{i}.xml", ws_xml)
