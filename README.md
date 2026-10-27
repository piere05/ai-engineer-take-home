# Lab-report extraction

## Run

Python 3.10+, Poppler (`pdftoppm`, `pdftotext`) and Tesseract OCR are required. Install Tesseract/Poppler with your OS package manager; then:

```bash
python -m venv .venv
# activate the environment, then:
python -m pip install -r requirements.txt
python extract.py reports/report_01.pdf
python eval.py --mode both
python -m unittest discover -s tests -v
```

The required CLI remains `python extract.py <file>` and writes JSON to stdout. PDF text is extracted directly when available; scanned PDFs use 200-DPI rendering and two Tesseract segmentation modes. Images are upscaled, contrast-normalized and OCR'd locally. No network calls or API keys are used; estimated external API spend is **$0/report**. Local compute/electricity is excluded from that cost figure. The parser preserves qualitative values and does not infer missing reference ranges or clinical status.

## Evaluation and results

Eight labelled reports (138 gold rows) are scored with a fixed one-to-one fuzzy test-name match, followed by value/unit/reference-range comparisons. Numeric formatting is normalized; unit/range comparisons remain conservative. Exact-row accuracy is exact value + unit + range among matched rows, divided by all gold rows. `eval.py` writes per-report predictions and metrics under `results/`.

**Important baseline caveat:** the supplied Gemini extractor could not be executed because no API key was supplied. The reproducible baseline below is a *local control* that uses the same parser/evaluator but restricts PDFs to page 1 and uses 60-DPI OCR for scanned PDFs, approximating two baseline input limitations. It is not a measured result for Gemini. This distinction is intentional; no model performance is fabricated.

| Metric | Local baseline control | Improved local pipeline | Change |
|---|---:|---:|---:|
| Row precision | 90.0% | 92.5% | +2.5 pp |
| Row recall | 58.7% | 89.1% | +30.4 pp |
| Exact-row accuracy / all gold rows | 54.4% | 73.9% | +19.6 pp |
| Value accuracy on matched rows | 96.3% | 93.5% | -2.8 pp |
| Unit accuracy on matched rows | 95.1% | 88.6% | -6.4 pp |
| Reference-range accuracy on matched rows | 98.8% | 94.3% | -4.5 pp |
| Mean latency/report | 0.59 s | 3.49 s | 5.93x slower |
| External API cost/report | $0.00 | $0.00 | unchanged |

The improvement is mainly **coverage**, not uniformly better field accuracy. The final pipeline extracts 123/138 labelled rows versus 81/138 for the control. Its two OCR passes cost more time and can introduce noisy duplicate candidates; the parser merges exact same-name/value duplicates, but OCR errors remain. Latencies are single local runs over this small set and will vary with CPU and installed tools. No cloud/model token cost applies.

### Main failure categories

1. **Page coverage.** The baseline control sees only page 1. On `report_11.pdf`, it produced 30 rows against 54 gold rows; the all-page pipeline produced 54, with 48 exact rows. This is a general page-coverage fix, not a report-specific rule.
2. **Scanned tables and OCR ambiguity.** On scanned `report_05.pdf`, the control produced 5 rows and matched none; the improved pipeline produced 13 rows, matched 10, and had 3 exact rows. OCR still confuses decimal points (`28.3`/`283`), abbreviations and units. `report_06.pdf` has two side-by-side tables; the final pipeline found 9 rows but none were exact, showing that extra OCR text alone is not enough when table structure is ambiguous.
3. **Unsupported assumptions / output semantics.** The original prompt asks the model to invent standard ranges when absent and forces every result to be numeric. `gold/report_03.json` explicitly has null ranges for T3 and T4, and `report_06.pdf` includes qualitative values such as Colour/Clarity. The replacement preserves string values and missing ranges, and rejects prescription instructions rather than interpreting medication doses as lab tests.

### Label audit and unlabelled reports

The gold labels are not treated as infallible. For example, `report_01.pdf` visibly prints Platelet Count `340000`, while `gold/report_01.json` says `304000`; the gold file was left unchanged so the evaluation remains reproducible, and the exact-row score penalizes this disagreement. Four unlabelled reports are saved under `results/unlabelled/` and are **qualitative review only**, not included in accuracy. `report_04` yielded 9 plausible rows; `report_07` yielded 9 rows but has suspicious OCR values/units requiring human review; `report_10` is poor OCR and not reliable without review; `report_12` is a clinical note/prescription rather than a lab-result report and correctly yields an empty `tests` array after prescription filtering.

### Failed experiment

Using Tesseract PSM 3 alone did not solve the scanned-table problem: on `report_06.pdf` it yielded 5 predictions, 2 matched rows and 0 exact rows; PSM 6 yielded 6 predictions, 3 matched rows and 0 exact rows. The pipeline keeps both modes because they recover complementary rows on other scanned reports, but the `report_06` result is an explicit remaining failure, not a claimed win.

## Architecture choices

- **RAG:** Not justified as a first fix. The task is to read the report, not retrieve medical facts. Retrieval could inject a generic range that contradicts the lab's printed interval; the safer behavior is to preserve a missing range as `null`.
- **Fine-tuning:** Not justified with eight labelled reports. First collect more diverse, adjudicated labels and measure recurring errors that remain after OCR/layout fixes; otherwise the model could overfit report templates and the noisy labels.
- **Multi-step agent:** Not earned yet. A deterministic local OCR → row parser → JSON pipeline is cheap and reproducible. A second pass should be added only for low-confidence rows if an experiment shows meaningful exact-row gains worth the extra latency.

## Decision log

- Kept `extract.py` as the required entry point and removed the API dependency to make the exercise runnable without paid access or secrets.
- Chose local PDF text extraction before OCR because digital PDF text is cleaner and faster; scanned pages use two segmentation modes because neither mode dominates on every table.
- Rejected inferred ranges/status and numeric-only coercion as unsafe for faithful extraction.
- Reviewed representative outputs across the 12 reports, inspected the report 01 label discrepancy, checked the 2-page report 11 row count, and added parser tests for missing ranges, qualitative values, metadata and prescriptions.
- The extractor makes no LLM calls, so there is no extraction-model prompt or API transcript. The code was developed with AI assistance, but no separate coding-agent transcript was exported. The key trade-off is transparent: zero API spend and reproducibility, but weaker performance on difficult scanned/table layouts than a strong vision model may achieve.
