"""Tests for recorded completion batches, loaded without any network code."""

from datetime import datetime
from datetime import timezone
import json
import subprocess
import sys
from typing import Any

from pydantic import ValidationError
import pytest

from dfilterforge.canonical import canonical_json
from dfilterforge.completions import CatalogIdentityV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import ConditionRunV1
from dfilterforge.completions import InvocationV1
from dfilterforge.completions import PreparedConditionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RequestSettingsV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import TokenPricesV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import RetrievalV1

_MOMENT = datetime(2026, 9, 18, 7, 30, tzinfo=timezone.utc)

_LOAD_WITHOUT_NETWORK = """
import sys
from dfilterforge.completions import CompletionBatchV1
batch = CompletionBatchV1.model_validate_json(sys.stdin.read())
assert batch.completions[0].reasoning_tokens == 0
loaded = {"http.client", "ssl", "dfilterforge.model_client"} & set(sys.modules)
print(sorted(loaded))
"""
_STORED_BATCH = """{
  "schema_version": "completion-batch/1.0",
  "output_contract": "display_filter",
  "retrieval": "none",
  "endpoint_kind": "openai-compatible-chat-completions",
  "settings": {"model_id": "qwen/qwen3-8b"},
  "completions": [{"item_id": "mei-0001", "status": "failed",
                   "error_code": "empty_content", "latency_ms": 812.5,
                   "http_status": 200, "finish_reason": "length",
                   "completion_tokens": 2048, "reasoning_tokens": 0}]
}"""


def test_stored_batches_load_without_the_network_stack() -> None:
    loaded = subprocess.run(
        [sys.executable, "-c", _LOAD_WITHOUT_NETWORK],
        input=_STORED_BATCH,
        capture_output=True,
        check=True,
        text=True,
        timeout=60,
    )

    assert loaded.stdout.strip() == "[]"


@pytest.mark.parametrize(
    "overrides",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": 301},
        {"timeout_seconds": float("nan")},
        {"temperature": 2.5},
        {"temperature": float("inf")},
        {"max_output_tokens": 0},
        {"max_output_tokens": 65_537},
        {"seed": True},
        {"seed": -1},
        {"seed": 2**31},
        {"model_id": "   "},
        {"api_key": "sk-must-not-live-here"},
        {"openrouter": {"provider_order": ["Alibaba"]}},
        {"openrouter": {"provider_order": ["a", "a"]}},
        {"openrouter": {"provider_order": ["a", "b", "c", "d", "e"]}},
        {"openrouter": {"reasoning": "exclude"}},
        {"openrouter": {"sort": "price"}},
    ],
)
def test_request_settings_are_bounded(overrides: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        RequestSettingsV1.model_validate({"model_id": "m", **overrides})


@pytest.mark.parametrize(
    "record",
    [
        {"status": "completed"},
        {"status": "completed", "response_text": "t", "error_code": "x"},
        {
            "status": "completed",
            "response_text": "t",
            "provider_error_code": "502",
        },
        {"status": "failed", "error_code": "x", "response_text": "t"},
        {"status": "failed"},
        {"status": "failed", "error_code": "free text"},
        {
            "status": "failed",
            "error_code": "x",
            "provider_error_code": "a" * 65,
        },
        {"status": "failed", "error_code": "x", "http_status": 99},
        {"status": "failed", "error_code": "x", "http_status": 1000},
        {"status": "failed", "error_code": "x", "finish_reason": "p" * 257},
        {"status": "failed", "error_code": "x", "response_model": "m" * 257},
        {"status": "failed", "error_code": "x", "provider": "p" * 257},
        {"status": "failed", "error_code": "x", "reasoning_tokens": -1},
        {
            "status": "failed",
            "error_code": "x",
            "cost_usd": float("nan"),
        },
        {"status": "failed", "error_code": "x", "cost_usd": 1500.0},
    ],
)
def test_completion_records_reject_ambiguous_or_unbounded_fields(
    record: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        CompletionV1.model_validate(
            {"item_id": "i", "latency_ms": 1.0, **record}
        )


def _prepare(**overrides: Any) -> PrepareManifestV1:
    """Builds one prepare manifest with the fixed dev shape."""
    values: dict[str, Any] = {
        "prepare_id": "prep-0001",
        "created_at": _MOMENT,
        "source_revision": "revision",
        "source_files": {"model_inputs.jsonl": "a" * 64},
        "split": "dev",
        "item_ids": ("mei-0001", "mei-0002"),
        "model_inputs_sha256": "b" * 64,
        "catalog": CatalogIdentityV1(
            file_name="fields.sqlite3.gz",
            file_sha256="c" * 64,
            sqlite_sha256="d" * 64,
            catalog_hash="e" * 64,
            tshark_version="4.6.8",
        ),
        "top_k": 8,
        "conditions": (
            PreparedConditionV1(
                label="C1",
                output_contract=OutputContractV1.DISPLAY_FILTER,
                retrieval=RetrievalV1.NONE,
                path="prepared/C1.json",
                sha256="f" * 64,
                system_prompt_sha256="0" * 64,
                prompt_count=2,
            ),
        ),
    }
    values.update(overrides)
    return PrepareManifestV1(**values)


def _run_manifest(**overrides: Any) -> RunManifestV1:
    """Builds one run manifest around an embedded prepare manifest."""
    values: dict[str, Any] = {
        "run_id": "dev-0001",
        "created_at": _MOMENT,
        "prepare": _prepare(),
        "prepare_sha256": "1" * 64,
        "endpoint_host": "openrouter.ai",
        "settings": RequestSettingsV1(model_id="vendor/model-a"),
        "prices": TokenPricesV1(
            usd_per_million_input=0.117,
            usd_per_million_output=0.455,
            source="openrouter 2026-09-17",
        ),
        "max_attempts": 3,
        "min_interval_seconds": 1.0,
        "invocations": (
            InvocationV1(
                source_revision="revision",
                source_files={"scripts/model_run.py": "2" * 64},
                started_at=_MOMENT,
                finished_at=_MOMENT,
                max_usd=5.0,
                requests_sent=4,
            ),
        ),
        "status": "complete",
        "charged_usd_upper_bound": 0.06,
        "provider_reported_usd": 0.0431,
        "conditions": (_condition(),),
    }
    values.update(overrides)
    return RunManifestV1(**values)


def _condition(**overrides: Any) -> ConditionRunV1:
    """Builds one finished condition of a run, files and census included."""
    values: dict[str, Any] = {
        "label": "C1",
        "attempts_path": "attempts/C1.jsonl",
        "attempts_sha256": "3" * 64,
        "completions_path": "completions/C1.json",
        "completions_sha256": "4" * 64,
        "attempts": {"mei-0001": 1, "mei-0002": 2},
        "completed": 2,
        "failed": 0,
        "pending": 0,
    }
    values.update(overrides)
    return ConditionRunV1(**values)


def test_run_manifest_round_trips_the_single_shape() -> None:
    """Every step reads the same run shape, with no restated fields."""
    manifest = _run_manifest()

    encoded = canonical_json(manifest)
    restored = RunManifestV1.model_validate_json(encoded)
    document: dict[str, Any] = json.loads(encoded)

    assert restored == manifest
    assert restored.prepare.split == "dev"
    assert restored.prices is not None
    assert restored.created_at == _MOMENT
    assert "split" not in document
    assert "prepare_id" not in document
    assert document["prepare"]["prepare_id"] == "prep-0001"


def test_a_held_out_prepare_manifest_is_unconstructible() -> None:
    """No held-out item can reach a model before the freeze commit."""
    with pytest.raises(ValidationError):
        _prepare(split="test")


@pytest.mark.parametrize(
    "overrides",
    [
        {"run_id": "test-0001"},
        {"run_id": "0001"},
        {"created_at": datetime(2026, 9, 18, 7, 30)},
        {"max_attempts": 6},
        {"max_attempts": 0},
        {"min_interval_seconds": 61.0},
        {"charged_usd_upper_bound": -1.0},
        {"provider_reported_usd": float("inf")},
        {"invocations": ()},
        {"conditions": ()},
    ],
)
def test_run_manifests_reject_unusable_identity_and_bounds(
    overrides: dict[str, Any],
) -> None:
    """The run identity and every safety bound are model invariants."""
    with pytest.raises(ValidationError):
        _run_manifest(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"attempts_path": "attempts/C4.jsonl"},
        {"attempts_path": "C1.jsonl"},
        {"completions_path": "completions/C4.json"},
        {"completions_path": None},
        {"completions_sha256": None},
        {"attempts_sha256": "3" * 63},
        {"completions_sha256": "z" * 64},
        {"completed": 1},
        {"pending": 1},
    ],
)
def test_condition_runs_name_their_own_files_and_count_their_own_items(
    overrides: dict[str, Any],
) -> None:
    """A condition that cannot describe itself is not a record of one."""
    with pytest.raises(ValidationError):
        _condition(**overrides)


@pytest.mark.parametrize(
    "conditions",
    [
        (_condition(), _condition()),
        (_condition(completions_path=None, completions_sha256=None),),
        (_condition(completed=1, pending=1),),
    ],
)
def test_a_complete_run_has_published_every_condition(
    conditions: tuple[ConditionRunV1, ...],
) -> None:
    """A published run cannot claim answers it never asked for."""
    with pytest.raises(ValidationError):
        _run_manifest(status="complete", conditions=conditions)


def test_an_incomplete_run_is_the_anchor_a_resume_reads() -> None:
    """The record a pass leaves before its first request is a valid one."""
    anchor = _run_manifest(
        status="incomplete",
        conditions=(
            _condition(
                completions_path=None,
                completions_sha256=None,
                completed=0,
                pending=2,
            ),
        ),
    )

    assert anchor.conditions[0].pending == 2
    assert anchor.conditions[0].completions_path is None


def test_a_run_records_a_bounded_number_of_invocations() -> None:
    """A run that was resumed without end is not a bounded record."""
    invocation = InvocationV1(
        source_revision="revision",
        source_files={"scripts/model_run.py": "2" * 64},
        started_at=_MOMENT,
        finished_at=_MOMENT,
        max_usd=5.0,
        requests_sent=4,
    )

    assert _run_manifest(invocations=(invocation,) * 32).invocations
    with pytest.raises(ValidationError):
        _run_manifest(invocations=(invocation,) * 33)


@pytest.mark.parametrize("max_usd", [0, 12.5, -1.0])
def test_invocation_budgets_stay_inside_the_project_cap(
    max_usd: float,
) -> None:
    """An invocation budget is bounded by the project's own spending cap."""
    with pytest.raises(ValidationError):
        InvocationV1(
            source_revision="revision",
            source_files={},
            started_at=_MOMENT,
            finished_at=_MOMENT,
            max_usd=max_usd,
            requests_sent=1,
        )


@pytest.mark.parametrize(
    "attempts",
    [
        {"mei-0001": 6},
        {"mei-0001": -1},
        {"not-an-item": 1},
        {},
    ],
)
def test_condition_runs_bound_their_attempt_census(
    attempts: dict[str, int],
) -> None:
    """Attempt keys are opaque item ids and values are bounded retries."""
    with pytest.raises(ValidationError):
        ConditionRunV1(
            label="C1",
            attempts_path="attempts/C1.jsonl",
            attempts_sha256="3" * 64,
            attempts=attempts,
            completed=1,
            failed=0,
            pending=0,
        )


def test_naive_invocation_timestamps_are_rejected() -> None:
    """A naive timestamp cannot be normalized, so it is refused."""
    with pytest.raises(ValidationError):
        InvocationV1(
            source_revision="revision",
            source_files={},
            started_at=datetime(2026, 9, 18, 7, 30),
            finished_at=_MOMENT,
            max_usd=5.0,
            requests_sent=1,
        )
