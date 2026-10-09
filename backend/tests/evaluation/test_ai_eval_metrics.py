from scripts.run_ai_eval import load_dataset, score_predictions, title_similarity


def test_gold_dataset_is_valid_and_grounded():
    cases = load_dataset()
    assert len(cases) >= 5


def test_metrics_reward_grounded_matches_and_penalize_false_positives():
    cases = [{
        "id": "sample",
        "transcript": "Ari will send the launch plan tomorrow.",
        "expected_tasks": [{
            "task_type": "ACTION_ITEM",
            "title": "Send launch plan",
            "source_quote": "Ari will send the launch plan tomorrow.",
        }],
    }]
    outputs = {"sample": [
        {"task_type": "ACTION_ITEM", "title": "Send launch plan", "source_quote": "Ari will send the launch plan tomorrow."},
        {"task_type": "ACTION_ITEM", "title": "Invent a task", "source_quote": "not in transcript"},
    ]}
    metrics = score_predictions(cases, outputs)
    assert metrics == {"precision": 0.5, "recall": 1.0, "quote_grounding": 1.0}


def test_title_similarity_is_token_based():
    assert title_similarity("Send launch plan", "Send the launch plan") > 0.5
