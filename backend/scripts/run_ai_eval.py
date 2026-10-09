"""Run the versioned meeting extraction gold set against the configured LLM."""

import argparse
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.agents.schemas import ExtractionResult, ExtractionState
from app.ai.prompts.catalog import EXTRACTION_SYSTEM_PROMPT
from app.clients.llm_gateway.client import get_gateway_client

DATASET = Path(__file__).resolve().parents[2] / "tests/evaluation/golden_meetings.jsonl"


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.casefold()))


def title_similarity(expected: str, actual: str) -> float:
    left, right = _tokens(expected), _tokens(actual)
    return len(left & right) / len(left | right) if left or right else 1.0


def score_predictions(cases: list[dict[str, Any]], outputs: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    expected_total = prediction_total = matched = grounded = 0
    for case in cases:
        expected = case["expected_tasks"]
        predicted = outputs.get(case["id"], [])
        expected_total += len(expected)
        prediction_total += len(predicted)
        available = set(range(len(predicted)))
        for target in expected:
            candidates = [
                (title_similarity(target["title"], predicted[index].get("title", "")), index)
                for index in available
                if target["task_type"] == predicted[index].get("task_type")
            ]
            if not candidates:
                continue
            similarity, index = max(candidates)
            if similarity < 0.45:
                continue
            matched += 1
            available.remove(index)
            quote = predicted[index].get("source_quote", "").strip()
            if quote and quote.casefold() in case["transcript"].casefold():
                grounded += 1

    precision = matched / prediction_total if prediction_total else float(expected_total == 0)
    recall = matched / expected_total if expected_total else float(prediction_total == 0)
    grounding = grounded / matched if matched else float(expected_total == 0 and prediction_total == 0)
    return {"precision": precision, "recall": recall, "quote_grounding": grounding}


def load_dataset() -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in DATASET.read_text().splitlines() if line.strip()]
    if not cases or len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Evaluation dataset must be non-empty and IDs must be unique")
    for case in cases:
        if not case.get("transcript") or not isinstance(case.get("expected_tasks"), list):
            raise ValueError(f"Invalid evaluation case: {case.get('id')}")
        for task in case["expected_tasks"]:
            if not all(task.get(field) for field in ("task_type", "title", "source_quote")):
                raise ValueError(f"Invalid gold task in case {case['id']}")
            if task["source_quote"].casefold() not in case["transcript"].casefold():
                raise ValueError(f"Gold quote is not grounded in case {case['id']}")
    return cases


async def evaluate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    gateway = await get_gateway_client()
    outputs: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        state = ExtractionState(
            meeting_id=case["id"], tenant_id="evaluation", user_id="evaluation",
            meeting_context=f"Evaluation case {case['id']}", transcript_chunks=[],
        )
        response = await gateway.chat_completion(
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": f"Transcript segment:\n{case['transcript']}\n\nExtract tasks, decisions, follow-ups, and blockers."},
            ],
            pipeline_node="extraction", tenant_id=state.tenant_id, user_id=state.user_id,
            meeting_id=state.meeting_id, use_cache=False,
            response_format={"type": "json_object"},
        )
        parsed = ExtractionResult.model_validate_json(response.content)
        outputs[case["id"]] = [task.model_dump() for task in parsed.tasks]
    metrics = score_predictions(cases, outputs)
    route = gateway.router.get_route("extraction")
    return {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256(EXTRACTION_SYSTEM_PROMPT.encode()).hexdigest(),
        "primary_model": route.primary,
        "fallback_models": route.fallback,
        "metrics": metrics,
        "outputs": outputs,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.80)
    parser.add_argument("--min-grounding", type=float, default=0.95)
    parser.add_argument("--baseline", type=Path, help="Compare metrics with a prior evaluation JSON report")
    parser.add_argument("--max-regression", type=float, default=0.03)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    cases = load_dataset()
    result = await evaluate(cases)
    encoded = json.dumps(result, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n")
    metrics = result["metrics"]
    passed_thresholds = (
        metrics["precision"] >= args.min_precision
        and metrics["recall"] >= args.min_recall
        and metrics["quote_grounding"] >= args.min_grounding
    )
    passed_regression = True
    if args.baseline:
        baseline = json.loads(args.baseline.read_text())["metrics"]
        for metric, value in metrics.items():
            if value < baseline[metric] - args.max_regression:
                print(
                    f"Regression gate failed for {metric}: {value:.3f} vs "
                    f"baseline {baseline[metric]:.3f} (allowed drop {args.max_regression:.3f})",
                    file=sys.stderr,
                )
                passed_regression = False
    return 0 if passed_thresholds and passed_regression else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
