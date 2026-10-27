# PLAN.md

## Objective
Improve lab-report extraction with reproducible evidence while preserving `python extract.py <file>` and the supplied JSON schema.

## Plan
1. Inspect the baseline, schema, all 12 reports and the eight supplied gold labels; identify available local OCR/PDF tools and record environment constraints.
2. Establish an evaluation harness with documented row matching, exact-row metrics, field-level accuracy and stable before/after rules. Run the original baseline where its API is available; otherwise distinguish code-level baseline findings from measured baseline results.
3. Inspect concrete mismatches and prioritize three generalizable failure classes: incomplete PDF page coverage, low-resolution/scanned inputs, and unsupported or malformed structured values.
4. Implement targeted fixes, retaining the CLI and schema, then run the same evaluation on the labelled subset and a qualitative review of unlabelled reports.
5. Measure per-report latency and estimated cost with the provider/model and environment stated explicitly. Record a failed experiment with evidence rather than inventing results.
6. Add tests, run instructions, architecture answers and a short decision log. Keep Git commits as work progresses and ensure no credentials are included.

## Initial hypotheses (to verify)
The baseline appears to process only page one at 60 DPI, asks the model to invent absent reference ranges, coerces qualitative results to numbers, and silently turns malformed model output into an empty list. Dataset-level impact must be measured, not assumed.

## Constraints and success criteria
Keep the change small; preserve the required entry point and schema; avoid report-specific hardcoding; report precision, recall, exact-row and field-level accuracy, latency and cost using unchanged evaluation rules. Do not claim an improvement unless measured evidence supports it.
