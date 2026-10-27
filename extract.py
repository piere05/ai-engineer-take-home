"""Extract lab-report result rows using local PDF text extraction and OCR.

Usage: python extract.py <path-to-report>
Prints JSON matching schema.json to stdout. No API key or network access is used.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp"}
VALUE_RE = re.compile(r"^[+-]?(?:\d[\d,]*(?:\.\d+)?|\.\d+)(?:\s*%?)$")
RANGE_RE = re.compile(r"(?:<=|>=|<|>)?\s*\d[\d,]*(?:\.\d+)?\s*(?:-|–|—|to)\s*\d[\d,]*(?:\.\d+)?|(?:<=|>=|<|>)\s*\d[\d,]*(?:\.\d+)?", re.I)
UNIT_RE = re.compile(r"^(?:%|[a-zA-Zµμ/][a-zA-Z0-9µμ/%._^()-]*)$")


def _run(args: list[str], timeout: int = 90) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required local tool not found: {args[0]}. See README.md.") from exc
    except subprocess.CalledProcessError as exc:
        message = exc.stderr.strip()[-500:] if exc.stderr else str(exc)
        raise RuntimeError(f"Command failed ({args[0]}): {message}") from exc


def _pdf_text(path: Path) -> str:
    if shutil.which("pdftotext"):
        result = _run(["pdftotext", "-layout", str(path), "-"])
        text = result.stdout
        if len(re.sub(r"\s", "", text)) > 80:
            return text
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise RuntimeError("Scanned PDF needs Poppler (pdftoppm) and Tesseract OCR; see README.md.")
    pages: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        prefix = str(Path(tmp) / "page")
        _run(["pdftoppm", "-r", "200", "-png", str(path), prefix], timeout=180)
        for image in sorted(Path(tmp).glob("page-*.png"), key=lambda p: int(re.search(r"-(\d+)$", p.stem).group(1))):
            # Table layouts vary; two Tesseract segmentation modes recover complementary rows.
            pages.append(_run(["tesseract", str(image), "stdout", "--psm", "6"], timeout=120).stdout or "")
            pages.append(_run(["tesseract", str(image), "stdout", "--psm", "3"], timeout=120).stdout or "")
    return "\n".join(pages)


def _ocr_image(path: Path) -> str:
    if not shutil.which("tesseract"):
        raise RuntimeError("Image extraction needs Tesseract OCR; see README.md.")
    try:
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        with Image.open(path) as source:
            image = ImageOps.grayscale(source)
            image = ImageOps.autocontrast(image)
            image = image.resize((image.width * 2, image.height * 2))
            image = ImageEnhance.Contrast(image).enhance(1.25)
            image = image.filter(ImageFilter.SHARPEN)
            with tempfile.TemporaryDirectory() as tmp:
                prepared = Path(tmp) / "prepared.png"
                image.save(prepared)
                return _run(["tesseract", str(prepared), "stdout", "--psm", "6"], timeout=120).stdout
    except ImportError:
        return _run(["tesseract", str(path), "stdout", "--psm", "6"], timeout=120).stdout


def _image_text(path: Path) -> str:
    return _ocr_image(path)


def _normalise_range(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().replace("–", "-").replace("—", "-")
    value = re.sub(r"\s*([<>])\s*", r"\1 ", value)
    value = re.sub(r"\s*-\s*", " - ", value)
    return re.sub(r"\s+", " ", value).strip() or None


def _clean_value(value: str) -> str | int | float | None:
    value = value.strip().strip("|:;,*")
    value = re.sub(r"\s+", " ", value)
    if not value or value.lower() in {"-", "—", "na", "n/a", "not done"}:
        return None
    if re.fullmatch(r"[+-]?\d[\d,]*(?:\.\d+)?", value):
        numeric = value.replace(",", "")
        try:
            return float(numeric) if "." in numeric else int(numeric)
        except ValueError:
            pass
    return value


def _split_columns(line: str) -> list[str]:
    # OCR often uses pipes; digital PDFs preserve columns as runs of spaces.
    if "|" in line:
        return [re.sub(r"\s+", " ", c).strip(" \t:;|") for c in line.split("|") if c.strip(" \t:;|")]
    cols = [re.sub(r"\s+", " ", c).strip(" \t:;|") for c in re.split(r"\s{2,}", line.strip()) if c.strip(" \t:;|")]
    return cols if len(cols) >= 2 else []


QUALITATIVE_VALUES = {
    "negative", "positive", "trace", "nil", "present", "absent", "clear", "cloudy", "turbid",
    "dark yellow", "pale yellow", "yellow", "straw", "amber", "normal", "abnormal", "reactive",
    "non reactive", "non-reactive", "few", "many", "rare", "none", "not seen", "seen", "acidic",
    "alkaline", "colourless", "colorless", "light yellow", "moderate", "occasional",
}


def _is_numeric(value: str) -> bool:
    return bool(VALUE_RE.fullmatch(value.strip().replace(",", "")))


def _is_result(value: str) -> bool:
    cleaned = re.sub(r"\s+", " ", value.strip().lower())
    return _is_numeric(cleaned) or cleaned in QUALITATIVE_VALUES


def _row_from_columns(cols: list[str]) -> dict | None:
    if len(cols) < 3:
        return None
    cols = [c.strip(" :|-") for c in cols]
    name = cols[0]
    if len(name) < 2 or len(name) > 90 or re.search(
        r"patient name|sample id|collected on|reported on|referred by|reference range|test name|observed value|investigation|biological ref|address|main road|laborator|diagnostics|page \d|age\s*/?\s*sex|^test$|^result$|^unit$", name, re.I
    ):
        return None
    result_index = next((i for i in range(1, min(len(cols), 4)) if _is_result(cols[i])), None)
    if result_index is None:
        return None
    value = cols[result_index]
    remaining = cols[result_index + 1:]
    unit = None
    ref = None
    if len(remaining) >= 2:
        ref = " ".join(remaining[1:])
        unit = remaining[0] or None
    elif len(remaining) == 1:
        if RANGE_RE.fullmatch(remaining[0].strip()):
            ref = remaining[0]
        elif UNIT_RE.fullmatch(remaining[0].strip()):
            unit = remaining[0]
        elif _is_result(value):
            ref = remaining[0]
    if result_index > 1:
        name = " ".join(cols[:result_index])
    # A quantitative row without a unit or printed interval is too ambiguous to keep.
    if _is_numeric(value) and not unit and not ref:
        return None
    if len(name) < 2 or re.search(r"(?:road|street|bengaluru|chennai|hyderabad|mysuru|tumakuru|patient|sample id|collected|reported|referred)", name, re.I):
        return None
    return {"test_name": name.strip(), "value": _clean_value(value), "unit": unit, "reference_range": _normalise_range(ref)}


def _looks_like_value(value: str) -> bool:
    return _is_result(value)

def _row_from_line(line: str) -> dict | None:
    line = re.sub(r"[\u00a0\t]+", " ", line).strip()
    if not line or len(line) > 260:
        return None
    # Do not interpret prescriptions/dosing instructions as laboratory result rows.
    if re.search(r"\b(?:Rx|Tab\.?|Cap\.?|Syp\.?|Inj\.?|after\s*food|afterfood|before\s*food|for\s+\d+\s+days)\b", line, re.I):
        return None
    # Prefer a printed interval found anywhere on an OCR line. This avoids splitting
    # decimal ranges into fake columns when OCR spacing is inconsistent.
    matches = list(RANGE_RE.finditer(line))
    if matches:
        rm = matches[-1]
        ref = rm.group(0).strip().rstrip("|;:._ cC")
        prefix = line[:rm.start()].rstrip(" |:;._")
        value_matches = list(re.finditer(r"(?<![A-Za-z])(?:[+-]?\d[\d,]*(?:\.\d+)?|\.\d+)(?![A-Za-z])", prefix))
        if value_matches:
            vm = value_matches[-1]
            name = prefix[:vm.start()].strip(" :|;._-\"'“”‘’")
            value = vm.group(0)
            middle = prefix[vm.end():].strip(" :|;._-\"'“”‘’[]")
            unit = middle if middle and len(middle) <= 20 else None
            name = re.sub(r"^[^A-Za-z]+", "", name)
            if name and len(name) <= 90 and not re.search(
                r"patient name|sample id|collected on|reported on|reference range|test name|age\s*/?\s*sex|referred by|road|street|bengaluru|chennai|hyderabad|mysuru|laborator|diagnostics|page\s*\d", name, re.I
            ):
                return {"test_name": name, "value": _clean_value(value), "unit": unit, "reference_range": _normalise_range(ref)}
    cols = _split_columns(line)
    row = _row_from_columns(cols)
    if row:
        return row
    # Digital PDFs often place a result and unit in one column with no reference range.
    if len(cols) == 2 and len(cols[0]) >= 2:
        match = re.match(r"^([+-]?\d[\d,]*(?:\.\d+)?)\s+(.+?)\s*$", cols[1])
        if match and UNIT_RE.fullmatch(match.group(2).strip()):
            name = cols[0].strip(" :|;._-")
            if name and not re.search(r"patient|sample|age|sex|collected|reported|road|street|laborator|diagnostics", name, re.I):
                return {"test_name": name, "value": _clean_value(match.group(1)), "unit": match.group(2).strip(), "reference_range": None}
    # Fallback for numeric results with a printed unit but no reference interval.
    cols = [c.strip(" :|;._-") for c in re.split(r"\s{2,}|\|", line) if c.strip(" :|;._-")]
    if len(cols) >= 3:
        result_index = next((i for i in range(1, min(len(cols), 4)) if _is_numeric(cols[i])), None)
        if result_index is not None:
            name = " ".join(cols[:result_index]).strip(" :|;._-")
            value = cols[result_index]
            unit = " ".join(cols[result_index + 1:]).strip() or None
            if name and len(name) <= 90 and unit and not re.search(r"patient|sample|age|sex|collected|reported|road|street|laborator|diagnostics", name, re.I):
                return {"test_name": name, "value": _clean_value(value), "unit": unit, "reference_range": None}
    return None

def parse_results(text: str) -> list[dict]:
    rows: list[dict] = []
    positions: dict[tuple, int] = {}
    for line in text.splitlines():
        row = _row_from_line(line)
        if not row or not row.get("test_name") or row.get("value") is None:
            continue
        unit = row.get("unit")
        if unit:
            unit = re.sub(r"^[^A-Za-z%µμ/]+|[^A-Za-z0-9%µμ/()._-]+$", "", str(unit)).strip()
            if not UNIT_RE.fullmatch(unit):
                unit = None
            row["unit"] = unit or None
        row["test_name"] = re.sub(r"\s+", " ", row["test_name"]).strip(" :|;._-\'")

        # Same name/value detected by multiple OCR segmentation modes is merged;
        # repeated measurements with different values remain separate rows.
        name_key = re.sub(r"\W+", "", row["test_name"].lower())
        value_key = re.sub(r"\s+", "", str(row["value"]).lower()).replace(",", "")
        key = (name_key, value_key)
        if key not in positions:
            positions[key] = len(rows)
            rows.append(row)
        else:
            old = rows[positions[key]]
            if not old.get("unit") and row.get("unit"):
                old["unit"] = row["unit"]
            if not old.get("reference_range") and row.get("reference_range"):
                old["reference_range"] = row["reference_range"]
            if len(row["test_name"]) < len(old["test_name"]) and len(row["test_name"]) >= 2:
                old["test_name"] = row["test_name"]
    return rows


def extract(path: Path) -> dict:
    if not path.is_file():
        raise RuntimeError(f"Input file does not exist: {path}")
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _pdf_text(path)
    elif suffix in IMAGE_EXTENSIONS:
        text = _image_text(path)
    else:
        raise RuntimeError(f"Unsupported file type: {suffix}. Use PDF, JPG, PNG, TIFF or BMP.")
    tests = parse_results(text)
    # This is a local OCR/text extraction prototype. It intentionally does not infer absent ranges/status.
    return {"tests": tests}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        sys.exit(2)
    try:
        print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
