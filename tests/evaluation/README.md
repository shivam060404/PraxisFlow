# AI extraction evaluation

The committed golden set is in `backend/tests/evaluation/golden_meetings.jsonl`.
It covers explicit commitments, conditional follow-ups, decisions, blockers,
conversations with no actionable commitment, and ambiguous ownership. Each gold
task includes its expected type, concise title, and an exact transcript quote.

Run the deterministic dataset and metric checks with the normal backend test
suite. Run the live model evaluation from the repository root with:

```sh
cd backend
GROQ_API_KEY=... python scripts/run_ai_eval.py
```

The live evaluator uses the configured extraction prompt and gateway route. It
reports task precision, recall, and exact quote grounding, and exits non-zero
when any threshold fails. Default release thresholds are precision >= 0.80,
recall >= 0.80, and quote grounding >= 0.95. Save a result for comparison with
`--output eval-results.json`; each report records dataset/prompt hashes and the
selected model route. Keep a prior report and pass `--baseline path.json` to
enforce a maximum metric drop (default 0.03) alongside the absolute thresholds.
Compare results whenever changing prompts, model routes, schemas, chunking, or
verification policy. Review the matched examples, not only aggregate scores,
before accepting a change.

This is a small regression set, not a statistically representative benchmark.
Production readiness still requires a larger consented, redacted, domain-
stratified corpus, reviewer adjudication, repeated runs for model variance,
and quality results by language, meeting length, and task type.
