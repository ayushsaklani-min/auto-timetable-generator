"""Import subject/faculty documents into the Step 2 course paste format."""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import Iterable, Optional
from xml.etree import ElementTree as ET

from ..models.domain import CourseType
from .from_paste import ParsedCourse, parse_courses_text

_DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
_COURSE_CODE_RE = re.compile(r"\b([A-Z]{2,}[A-Z0-9_/-]*\d[A-Z0-9_/-]*)\b")
_HEADER_LINES = [
    "# CODE, NAME, CREDITS, TYPE, FACULTY1; FACULTY2; ...",
    "# TYPE: theory | lab | lab pair=CODE | activity | activity locked=DAY:slots | combined",
    "# Faculty: list one per section in order, or 'auto', 'xN', or 'same-as=CODE'",
    "",
]
_HEADER_ALIASES = {
    "code": ["course code", "subject code", "paper code", "code"],
    "name": ["course name", "subject name", "subject", "course", "title", "paper"],
    "credits": ["credits", "credit", "credits/hrs", "credit hrs", "hrs", "hours"],
    "type": ["type", "category", "mode", "kind"],
    "faculty": ["faculty", "faculties", "teacher", "teachers", "staff", "instructor", "handled by"],
}


@dataclass
class DraftCourseRow:
    code: str
    name: str
    credits: int
    kind: str
    pair_course: str = ""
    locked_day: str = ""
    locked_slots: list[int] = field(default_factory=list)
    combined: bool = False
    faculty_directive: str = ""
    faculty_names: list[str] = field(default_factory=list)


@dataclass
class ImportedRow:
    code: str = ""
    name: str = ""
    credits: Optional[int] = None
    kind: str = ""
    faculty_names: list[str] = field(default_factory=list)


@dataclass
class DocumentImportSummary:
    filename: str
    format: str
    course_rows: int = 0
    faculty_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def import_course_documents(
    files: list[tuple[str, bytes]],
    section_ids: list[str],
    existing_text: str = "",
    replace_existing: bool = True,
) -> dict:
    base_rows = [] if replace_existing else _parse_existing_rows(existing_text)
    course_index = {row.code.upper(): row for row in base_rows if row.code.strip()}
    name_index = {_course_name_key(row.name): row for row in base_rows if row.name.strip()}

    documents: list[DocumentImportSummary] = []
    warnings: list[str] = []
    imported_rows = 0
    imported_faculty = 0

    def upsert(candidate: ImportedRow) -> None:
        nonlocal imported_rows, imported_faculty
        if not candidate.code.strip() and not candidate.name.strip():
            return
        target: Optional[DraftCourseRow] = None
        code_key = candidate.code.upper().strip()
        if code_key:
            target = course_index.get(code_key)
        if target is None and candidate.name.strip():
            target = name_index.get(_course_name_key(candidate.name))

        if target is None:
            target = DraftCourseRow(
                code=(candidate.code or _slugify(candidate.name) or f"COURSE_{len(base_rows) + 1}").upper(),
                name=candidate.name.strip() or candidate.code.strip() or f"Course {len(base_rows) + 1}",
                credits=candidate.credits or _default_credits(candidate.kind, candidate.name, candidate.code),
                kind=candidate.kind or _infer_kind(candidate.name, candidate.code),
            )
            base_rows.append(target)
            course_index[target.code.upper()] = target
            name_index[_course_name_key(target.name)] = target
            imported_rows += 1

        if candidate.name.strip():
            target.name = candidate.name.strip()
            name_index[_course_name_key(target.name)] = target
        if candidate.credits is not None:
            target.credits = max(0, int(candidate.credits))
        if candidate.kind:
            target.kind = candidate.kind
        if candidate.faculty_names:
            target.faculty_names = _merge_faculty_names(target.faculty_names, candidate.faculty_names)
            target.faculty_directive = ""
            imported_faculty += 1

    for filename, data in files:
        summary = _parse_document(filename, data, section_ids)
        documents.append(summary["summary"])
        warnings.extend(summary["summary"].warnings)
        for row in summary["rows"]:
            upsert(row)

    if not base_rows:
        raise ValueError("No subject or faculty rows could be recognised from the uploaded files.")

    raw_text = _serialize_rows(base_rows)
    return {
        "raw_text": raw_text,
        "summary": {
            "documents": len(documents),
            "courses": len(base_rows),
            "imported_courses": imported_rows,
            "faculty_mappings": imported_faculty,
        },
        "documents_info": [
            {
                "filename": doc.filename,
                "format": doc.format,
                "course_rows": doc.course_rows,
                "faculty_rows": doc.faculty_rows,
                "warnings": doc.warnings,
            }
            for doc in documents
        ],
        "warnings": warnings,
    }


def _parse_existing_rows(text: str) -> list[DraftCourseRow]:
    try:
        parsed = parse_courses_text(text)
    except Exception:
        return []
    return [_parsed_to_draft(row) for row in parsed]


def _parsed_to_draft(row: ParsedCourse) -> DraftCourseRow:
    faculty_directive = row.faculty_spec.strip()
    faculty_names: list[str] = []
    if faculty_directive and not _is_faculty_directive(faculty_directive):
        faculty_names = _split_faculty_names(faculty_directive)
        faculty_directive = ""
    return DraftCourseRow(
        code=row.code,
        name=row.name,
        credits=row.credits,
        kind=_kind_label(row.type),
        pair_course=row.pair_course or "",
        locked_day=row.locked_day or "",
        locked_slots=list(row.locked_slots or []),
        combined=row.is_combined,
        faculty_directive=faculty_directive,
        faculty_names=faculty_names,
    )


def _kind_label(kind: CourseType) -> str:
    if kind is CourseType.LAB:
        return "lab"
    if kind is CourseType.ACTIVITY:
        return "activity"
    return "theory"


def _parse_document(filename: str, data: bytes, section_ids: list[str]) -> dict:
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    summary = DocumentImportSummary(filename=filename, format=ext or "unknown")
    rows: list[ImportedRow] = []

    if ext == "pdf":
        tables, lines = _extract_pdf(data)
    elif ext == "docx":
        tables, lines = _extract_docx(data)
    else:
        raise ValueError(f"Unsupported file type for {filename!r}. Upload PDF or DOCX files.")

    seen = set()
    for table in tables:
        for row in _parse_table_rows(table, section_ids):
            key = (row.code.upper(), row.name.upper(), tuple(row.faculty_names))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if row.code or row.name:
                summary.course_rows += 1
            if row.faculty_names:
                summary.faculty_rows += 1

    line_tables = _collect_line_tables(lines)
    for table in line_tables:
        for row in _parse_table_rows(table, section_ids):
            key = (row.code.upper(), row.name.upper(), tuple(row.faculty_names))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if row.code or row.name:
                summary.course_rows += 1
            if row.faculty_names:
                summary.faculty_rows += 1

    free_text_hits = _parse_free_text(lines)
    for row in free_text_hits:
        key = (row.code.upper(), row.name.upper(), tuple(row.faculty_names))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
        if row.code or row.name:
            summary.course_rows += 1
        if row.faculty_names:
            summary.faculty_rows += 1

    if not rows:
        summary.warnings.append(
            "No structured rows were recognised. Use documents with course/faculty tables for best results."
        )

    return {"summary": summary, "rows": rows}


def _extract_pdf(data: bytes) -> tuple[list[list[list[str]]], list[str]]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    lines: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        lines.extend(_clean_lines(text.splitlines()))
    return [], lines


def _extract_docx(data: bytes) -> tuple[list[list[list[str]]], list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml")
    root = ET.fromstring(xml)

    tables: list[list[list[str]]] = []
    for tbl in root.findall(".//w:tbl", _DOCX_NS):
        parsed_rows: list[list[str]] = []
        for tr in tbl.findall("./w:tr", _DOCX_NS):
            row: list[str] = []
            for tc in tr.findall("./w:tc", _DOCX_NS):
                text = " ".join(t.text or "" for t in tc.findall(".//w:t", _DOCX_NS)).strip()
                row.append(_collapse_ws(text))
            if any(cell for cell in row):
                parsed_rows.append(row)
        if len(parsed_rows) >= 2:
            tables.append(parsed_rows)

    lines = []
    for para in root.findall(".//w:p", _DOCX_NS):
        text = " ".join(t.text or "" for t in para.findall(".//w:t", _DOCX_NS)).strip()
        if text:
            lines.append(_collapse_ws(text))
    return tables, _clean_lines(lines)


def _collect_line_tables(lines: list[str]) -> list[list[list[str]]]:
    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    expected_cols = 0

    for line in lines:
        parts = _split_tabular_line(line)
        if parts:
            if not current:
                current = [parts]
                expected_cols = len(parts)
                continue
            if abs(len(parts) - expected_cols) <= 2:
                current.append(parts)
                expected_cols = max(expected_cols, len(parts))
                continue
            if len(current) >= 2:
                groups.append(current)
            current = [parts]
            expected_cols = len(parts)
            continue
        if len(current) >= 2:
            groups.append(current)
        current = []
        expected_cols = 0

    if len(current) >= 2:
        groups.append(current)
    return groups


def _parse_table_rows(rows: list[list[str]], section_ids: list[str]) -> list[ImportedRow]:
    if len(rows) < 2:
        return []

    header_map = _map_headers(rows[0], section_ids)
    data_rows = rows[1:]
    parsed = _parse_with_header(header_map, data_rows)
    if parsed:
        return parsed
    return _parse_without_header(rows, section_ids)


def _map_headers(header: list[str], section_ids: list[str]) -> dict:
    mapped = {"code": None, "name": None, "credits": None, "type": None, "faculty": [], "section_faculty": []}
    section_lookup = {sid.strip().upper(): sid.strip().upper() for sid in section_ids if sid.strip()}

    for idx, raw in enumerate(header):
        cell = _canonical_header(raw)
        if not cell:
            continue
        for key, aliases in _HEADER_ALIASES.items():
            if any(alias in cell for alias in aliases):
                if key == "faculty":
                    mapped["faculty"].append(idx)
                elif mapped[key] is None:
                    mapped[key] = idx
                break
        else:
            section_id = _match_section_header(cell, section_lookup)
            if section_id:
                mapped["section_faculty"].append((section_id, idx))
    return mapped


def _parse_with_header(header_map: dict, rows: list[list[str]]) -> list[ImportedRow]:
    if (
        header_map["code"] is None
        and header_map["name"] is None
        and not header_map["faculty"]
        and not header_map["section_faculty"]
    ):
        return []

    parsed: list[ImportedRow] = []
    for row in rows:
        candidate = ImportedRow()
        if header_map["code"] is not None and header_map["code"] < len(row):
            candidate.code = _extract_course_code(row[header_map["code"]])
        if header_map["name"] is not None and header_map["name"] < len(row):
            candidate.name = row[header_map["name"]].strip()
        if header_map["credits"] is not None and header_map["credits"] < len(row):
            candidate.credits = _parse_int(row[header_map["credits"]])
        if header_map["type"] is not None and header_map["type"] < len(row):
            candidate.kind = _infer_kind(row[header_map["type"]], candidate.code)
        elif candidate.name or candidate.code:
            candidate.kind = _infer_kind(candidate.name, candidate.code)

        faculty_names: list[str] = []
        for idx in header_map["faculty"]:
            if idx < len(row):
                faculty_names.extend(_split_faculty_names(row[idx]))
        for _, idx in header_map["section_faculty"]:
            if idx < len(row):
                faculty_names.extend(_split_faculty_names(row[idx]))
        candidate.faculty_names = _merge_faculty_names([], faculty_names)

        if not candidate.code and candidate.name:
            candidate.code = _slugify(candidate.name).upper()

        if candidate.code or candidate.name or candidate.faculty_names:
            parsed.append(candidate)
    return parsed


def _parse_without_header(rows: list[list[str]], section_ids: list[str]) -> list[ImportedRow]:
    parsed: list[ImportedRow] = []
    if not rows:
        return parsed

    for row in rows:
        if not row:
            continue
        first = _extract_course_code(row[0])
        if not first:
            continue
        candidate = ImportedRow(code=first)
        if len(row) >= 2:
            candidate.name = row[1].strip()
        if len(row) >= 3:
            maybe_credits = _parse_int(row[2])
            if maybe_credits is not None:
                candidate.credits = maybe_credits
                if len(row) >= 4:
                    candidate.faculty_names = _merge_faculty_names([], _split_faculty_names(row[3]))
            else:
                candidate.faculty_names = _merge_faculty_names([], _split_faculty_names(row[2]))
                if len(row) >= 4:
                    candidate.faculty_names = _merge_faculty_names(
                        candidate.faculty_names,
                        _split_faculty_names(row[3]),
                    )
        candidate.kind = _infer_kind(candidate.name, candidate.code)
        parsed.append(candidate)
    return parsed


def _parse_free_text(lines: list[str]) -> list[ImportedRow]:
    parsed: list[ImportedRow] = []
    for line in lines:
        code = _extract_course_code(line)
        if not code:
            continue
        if re.search(r"\b(dr|prof|professor|faculty|instructor|teacher)\b", line, re.IGNORECASE):
            names = _split_faculty_names(line.replace(code, " "))
            if names:
                parsed.append(ImportedRow(code=code, faculty_names=names))
                continue
        credit_match = re.search(r"\b(\d{1,2})\b", line)
        title = line.replace(code, " ", 1)
        if credit_match:
            title = title.replace(credit_match.group(1), " ", 1)
        title = _collapse_ws(title.strip(" -:|"))
        if title:
            parsed.append(
                ImportedRow(
                    code=code,
                    name=title,
                    credits=int(credit_match.group(1)) if credit_match else None,
                    kind=_infer_kind(title, code),
                )
            )
    return parsed


def _serialize_rows(rows: Iterable[DraftCourseRow]) -> str:
    lines = list(_HEADER_LINES)
    for row in rows:
        kind_bits = [row.kind or _infer_kind(row.name, row.code)]
        if row.kind == "lab" and row.pair_course.strip():
            kind_bits.append(f"pair={row.pair_course.strip()}")
        if row.kind == "activity" and row.locked_day.strip() and row.locked_slots:
            slots = ",".join(str(slot) for slot in row.locked_slots)
            kind_bits.append(f"locked={row.locked_day.strip().upper()}:{slots}")
        if row.combined:
            kind_bits.append("combined")
        faculty_spec = row.faculty_directive.strip()
        if row.faculty_names:
            faculty_spec = "; ".join(row.faculty_names)
        elif not faculty_spec:
            faculty_spec = "auto"
        lines.append(
            f"{row.code.strip()}, {row.name.strip()}, {max(0, int(row.credits))}, {' '.join(kind_bits)}, {faculty_spec}"
        )
    return "\n".join(lines)


def _split_tabular_line(line: str) -> Optional[list[str]]:
    raw = line.strip()
    if not raw:
        return None
    for pattern in (r"\s*\|\s*", r"\t+", r" {2,}"):
        parts = [_collapse_ws(part) for part in re.split(pattern, raw) if _collapse_ws(part)]
        if len(parts) >= 2:
            return parts
    return None


def _split_faculty_names(value: str) -> list[str]:
    if not value:
        return []
    cleaned = re.sub(r"\b(and|&)\b", ",", value, flags=re.IGNORECASE)
    parts = re.split(r"[;\n|,/]+", cleaned)
    return [part.strip(" -:") for part in parts if part.strip(" -:")]


def _merge_faculty_names(current: list[str], incoming: list[str]) -> list[str]:
    seen = {_faculty_key(name) for name in current}
    out = list(current)
    for name in incoming:
        cleaned = _collapse_ws(name)
        if not cleaned:
            continue
        key = _faculty_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


def _extract_course_code(value: str) -> str:
    match = _COURSE_CODE_RE.search(value.upper())
    return match.group(1).strip() if match else ""


def _parse_int(value: str) -> Optional[int]:
    match = re.search(r"\d+", value or "")
    return int(match.group(0)) if match else None


def _default_credits(kind: str, name: str, code: str) -> int:
    inferred = kind or _infer_kind(name, code)
    if inferred == "lab":
        return 1
    if inferred == "activity":
        return 0
    return 3


def _infer_kind(name: str, code: str) -> str:
    text = f"{name} {code}".lower()
    if any(token in text for token in ("activity", "tutorial", "proctor", "remedial", "ncmc", "dept")):
        return "activity"
    if " lab" in text or text.endswith("_lab") or text.endswith("lab"):
        return "lab"
    return "theory"


def _is_faculty_directive(value: str) -> bool:
    lowered = value.lower().strip()
    return lowered == "auto" or lowered.startswith("x") or lowered.startswith("same-as=")


def _match_section_header(cell: str, section_lookup: dict[str, str]) -> str:
    if cell in section_lookup:
        return section_lookup[cell]
    m = re.match(r"(section|sec)\s*([a-z0-9]+)$", cell)
    if m:
        candidate = m.group(2).upper()
        return section_lookup.get(candidate, "")
    return ""


def _canonical_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").strip().lower()).strip()


def _course_name_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _faculty_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", (value or "").upper()).strip("_")
    return slug[:32]


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _clean_lines(lines: Iterable[str]) -> list[str]:
    out: list[str] = []
    for line in lines:
        cleaned = _collapse_ws(line)
        if cleaned:
            out.append(cleaned)
    return out
