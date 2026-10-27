"""Reproducible labelled-set evaluation: python eval.py [--mode final|baseline|both]."""
from __future__ import annotations
import argparse, difflib, json, re, shutil, subprocess, tempfile, time
from pathlib import Path
from extract import parse_results, _run

ROOT = Path(__file__).resolve().parent
GOLD = ROOT / "gold"
REPORTS = ROOT / "reports"


def baseline_text(path: Path) -> str:
    """Local control approximating the original's first-page/60-DPI input limitations.

    This is explicitly not a run of the Gemini baseline: no API key was supplied.
    It isolates first-page coverage and low-resolution OCR while keeping parser/eval fixed.
    """
    if path.suffix.lower() == ".pdf":
        if shutil.which("pdftotext"):
            text = _run(["pdftotext", "-f", "1", "-l", "1", "-layout", str(path), "-"]).stdout
            if len(re.sub(r"\s", "", text)) > 80:
                return text
        if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
            raise RuntimeError("Baseline OCR requires Poppler and Tesseract")
        with tempfile.TemporaryDirectory() as tmp:
            prefix = str(Path(tmp) / "page")
            _run(["pdftoppm", "-f", "1", "-l", "1", "-singlefile", "-r", "60", "-png", str(path), prefix], timeout=120)
            return _run(["tesseract", prefix + ".png", "stdout", "--psm", "6"], timeout=120).stdout
    return _run(["tesseract", str(path), "stdout", "--psm", "6"], timeout=120).stdout


def norm_name(s: str) -> str:
    s = s.lower().replace("haemoglobin", "hemoglobin").replace("haematocrit", "hematocrit")
    s = re.sub(r"\b(total|serum|count|level|direct|observed|value)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def norm_field(v) -> str:
    if v is None:
        return ""
    s = str(v).strip().lower().replace("µ", "u").replace("μ", "u").replace("–", "-").replace("—", "-")
    s = re.sub(r"\s+", "", s).replace(",", "")
    # Numeric equality ignores representational differences such as 13.0 vs 13.
    try:
        f = float(s)
        return str(round(f, 8))
    except ValueError:
        return s


def match_rows(pred: list[dict], gold: list[dict]) -> tuple[list[tuple[int,int]], set[int], set[int]]:
    pairs = []
    used_p, used_g = set(), set()
    candidates = []
    for gi, g in enumerate(gold):
        gn = norm_name(g.get("test_name", ""))
        for pi, p in enumerate(pred):
            pn = norm_name(p.get("test_name", ""))
            if not pn or not gn:
                continue
            ratio = difflib.SequenceMatcher(None, pn, gn).ratio()
            token_overlap = len(set(re.findall(r"[a-z]+", str(p.get("test_name", "")).lower())) & set(re.findall(r"[a-z]+", str(g.get("test_name", "")).lower())))
            if pn == gn or ratio >= 0.84 or (ratio >= 0.72 and token_overlap >= 2):
                candidates.append((ratio + (0.2 if pn == gn else 0), pi, gi))
    for _, pi, gi in sorted(candidates, reverse=True):
        if pi not in used_p and gi not in used_g:
            pairs.append((pi, gi)); used_p.add(pi); used_g.add(gi)
    return pairs, used_p, used_g


def evaluate(mode: str) -> dict:
    per_report = []
    totals = {k: 0 for k in ["pred_rows", "gold_rows", "matched", "exact", "value_correct", "unit_correct", "range_correct"]}
    for gold_path in sorted(GOLD.glob("report_*.json")):
        report_path = REPORTS / (gold_path.stem + ".pdf")
        if not report_path.exists():
            report_path = REPORTS / (gold_path.stem + ".jpg")
        gold = json.loads(gold_path.read_text(encoding="utf-8"))["tests"]
        started = time.perf_counter()
        if mode == "baseline":
            text = baseline_text(report_path)
            pred = parse_results(text)
        else:
            from extract import extract
            pred = extract(report_path)["tests"]
        latency = time.perf_counter() - started
        output_dir = ROOT / "results" / mode
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / f"{report_path.stem}.json").write_text(json.dumps({"tests": pred}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pairs, used_p, used_g = match_rows(pred, gold)
        fields = {"value": 0, "unit": 0, "reference_range": 0}
        exact = 0
        for pi, gi in pairs:
            p, g = pred[pi], gold[gi]
            for field in fields:
                if norm_field(p.get(field)) == norm_field(g.get(field)):
                    fields[field] += 1
            if all(norm_field(pred[pi].get(f)) == norm_field(gold[gi].get(f)) for f in ("value", "unit", "reference_range")):
                exact += 1
        totals["pred_rows"] += len(pred); totals["gold_rows"] += len(gold); totals["matched"] += len(pairs); totals["exact"] += exact
        totals["value_correct"] += fields["value"]; totals["unit_correct"] += fields["unit"]; totals["range_correct"] += fields["reference_range"]
        per_report.append({"report": report_path.name, "gold_rows": len(gold), "predicted_rows": len(pred), "matched_rows": len(pairs), "exact_rows": exact, "value_correct": fields["value"], "unit_correct": fields["unit"], "range_correct": fields["reference_range"], "latency_seconds": round(latency, 3), "unmatched_gold": [gold[i]["test_name"] for i in range(len(gold)) if i not in used_g], "unmatched_predictions": [pred[i]["test_name"] for i in range(len(pred)) if i not in used_p]})
    pred_n, gold_n, matched = totals["pred_rows"], totals["gold_rows"], totals["matched"]
    out = {
        "mode": mode,
        "notes": "baseline is a local first-page/60-DPI OCR control, not the original Gemini model; the Gemini API baseline could not be run without a supplied key.",
        "reports_evaluated": len(per_report),
        "row_precision": round(matched / pred_n, 4) if pred_n else 0,
        "row_recall": round(matched / gold_n, 4) if gold_n else 0,
        "exact_row_accuracy_over_gold": round(totals["exact"] / gold_n, 4) if gold_n else 0,
        "value_accuracy_on_matched_rows": round(totals["value_correct"] / matched, 4) if matched else 0,
        "unit_accuracy_on_matched_rows": round(totals["unit_correct"] / matched, 4) if matched else 0,
        "reference_range_accuracy_on_matched_rows": round(totals["range_correct"] / matched, 4) if matched else 0,
        "mean_latency_seconds_per_report": round(sum(r["latency_seconds"] for r in per_report) / len(per_report), 3) if per_report else 0,
        "totals": totals,
        "per_report": per_report,
    }
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["baseline", "final", "both"], default="both")
    parser.add_argument("--out", default="results")
    args = parser.parse_args()
    outdir = ROOT / args.out
    outdir.mkdir(parents=True, exist_ok=True)
    modes = ["baseline", "final"] if args.mode == "both" else [args.mode]
    summaries = {}
    for mode in modes:
        result = evaluate(mode)
        target = outdir / f"{mode}_metrics.json"
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        summaries[mode] = result
        print(f"{mode}: precision={result['row_precision']:.1%}, recall={result['row_recall']:.1%}, exact-row={result['exact_row_accuracy_over_gold']:.1%}, mean-latency={result['mean_latency_seconds_per_report']:.2f}s")
    if len(summaries) == 2:
        (outdir / "comparison.json").write_text(json.dumps(summaries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
