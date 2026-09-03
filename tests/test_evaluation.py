"""Tests for packet-set metrics and immutable receipts."""

from datetime import datetime
from datetime import timezone

from pydantic import ValidationError
import pytest

from dfilterforge.evaluation import aggregate_metrics
from dfilterforge.evaluation import EnvironmentManifestV1
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.evaluation import EvaluationReceiptV1
from dfilterforge.evaluation import ProbeExpectationV1
from dfilterforge.evaluation import ProbeResultV1
from dfilterforge.evaluation import SemanticSpecV1
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate


def test_packet_diff_and_metrics() -> None:
    result = evaluate_probe("probe-a", [1, 2, 4], [2, 3, 4], 12.5)

    assert result.intersection == (2, 4)
    assert result.reference_only == (1,)
    assert result.candidate_only == (3,)
    assert abs(result.precision - (2 / 3)) < 1e-12
    assert abs(result.recall - (2 / 3)) < 1e-12
    assert abs(result.f1 - (2 / 3)) < 1e-12
    assert abs(result.jaccard - (1 / 2)) < 1e-12
    assert result.exact is False


def test_empty_set_coincidence_is_not_strong_exact() -> None:
    empty = evaluate_probe("empty", [], [], 1.0)
    matched = evaluate_probe("matched", [1], [1], 2.0)

    metrics = aggregate_metrics((empty, matched))

    assert empty.exact is True
    assert empty.empty_set_coincidence is True
    assert metrics.strong_exact_count == 1
    assert metrics.empty_set_coincidence_count == 1


def test_receipt_rejects_tampered_metrics() -> None:
    probe = evaluate_probe("probe", [1], [1], 1.0)
    metrics = aggregate_metrics((probe,))
    bad_metrics = metrics.model_copy(update={"macro_f1": 0.0})

    with pytest.raises(ValidationError, match="metrics do not match"):
        EvaluationReceiptV1(
            run_id="run-1",
            created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
            code_revision="abc",
            environment_hash="environment",
            data_hash="data",
            candidate_filter="tcp",
            reference_filter="tcp",
            probes=(probe,),
            metrics=bad_metrics,
        )


def test_receipt_hash_is_stable_across_round_trip() -> None:
    probe = evaluate_probe("probe", [3, 1], [1, 3], 1.0)
    receipt = EvaluationReceiptV1(
        run_id="run-1",
        created_at=datetime(2026, 9, 2, tzinfo=timezone.utc),
        code_revision="abc",
        environment_hash="environment",
        data_hash="data",
        candidate_filter="tcp",
        reference_filter="tcp",
        probes=(probe,),
        metrics=aggregate_metrics((probe,)),
    )

    restored = EvaluationReceiptV1.model_validate_json(
        receipt.model_dump_json()
    )

    assert restored.receipt_hash() == receipt.receipt_hash()


def test_packet_set_edge_conventions() -> None:
    missing = evaluate_probe("missing", [1], [], 1.0)
    extra = evaluate_probe("extra", [], [1], 1.0)

    assert (missing.precision, missing.recall) == (0.0, 0.0)
    assert (extra.precision, extra.recall) == (0.0, 0.0)


def test_probe_rejects_invalid_frame_sets_and_derived_values() -> None:
    with pytest.raises(ValidationError, match="unique"):
        evaluate_probe("duplicate", [1, 1], [1], 1.0)
    with pytest.raises(ValidationError, match="positive"):
        evaluate_probe("negative", [0], [], 1.0)
    with pytest.raises(ValidationError, match="precision does not match"):
        ProbeResultV1(
            probe_id="tampered",
            expected_frames=(1,),
            candidate_frames=(1,),
            runtime_ms=1,
            intersection=(1,),
            exact=True,
            precision=0,
            recall=1,
            f1=1,
            jaccard=1,
        )


def test_aggregate_requires_a_probe() -> None:
    with pytest.raises(ValueError, match="at least one"):
        aggregate_metrics(())


def test_environment_hash_changes_with_execution_settings() -> None:
    manifest = EnvironmentManifestV1(
        tshark_version="4.6.8",
        image_digest="sha256:image",
        profile_hash="profile",
        catalog_hash="catalog",
    )
    two_pass = manifest.model_copy(update={"pass_mode": "two-pass"})

    assert manifest.environment_hash() != two_pass.environment_hash()


def test_semantic_spec_rejects_duplicate_probe_ids() -> None:
    intent = IntentIrV1(
        expression=Predicate(field="tcp", operator=Operator.EXISTS)
    )
    probe = ProbeExpectationV1(
        probe_id="same", capture_sha256="capture", expected_frames=(1,)
    )

    with pytest.raises(ValidationError, match="probe IDs must be unique"):
        SemanticSpecV1(
            task_id="task",
            intent="Show TCP packets.",
            canonical_ir=intent,
            reference_filter="tcp",
            probes=(probe, probe),
            split="test",
            provenance="generated",
            license="CC-BY-4.0",
            review_status="reviewed",
        )


def test_receipt_requires_aware_timestamp() -> None:
    probe = evaluate_probe("probe", [1], [1], 1.0)

    with pytest.raises(ValidationError, match="timezone"):
        EvaluationReceiptV1(
            run_id="run-1",
            created_at=datetime(2026, 9, 2),
            code_revision="abc",
            environment_hash="environment",
            data_hash="data",
            candidate_filter="tcp",
            reference_filter="tcp",
            probes=(probe,),
            metrics=aggregate_metrics((probe,)),
        )
