"""Every hosted test run is registered before the first test request.

``docs/decisions/evidence/test-runs.json`` and the note beside it name each
run over the frozen test prompts: its role, run id, model, config, cap and
the run whose failure would trigger it. These tests read the committed
docs/ tree, which the test image does not carry, so they skip there.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys
from types import ModuleType
from typing import Any

import pytest

from dfilterforge import held_out
from dfilterforge.generation import PreparedBatchV1

_ROOT = Path(__file__).resolve().parents[1]
_DECISIONS = _ROOT / "docs" / "decisions"
_REGISTRY = _DECISIONS / "evidence" / "test-runs.json"
_NOTE = _DECISIONS / "test-runs.md"
_RULING = _DECISIONS / "evidence" / "bakeoff" / "ruling-2026-10-01.json"
_NO_DOCS = "the test image carries no docs/ tree"
_PREPARE = "docs/results/test-qwen3-32b-2026-09-26"
_DATE = "2026-09-26"
# The tags other run ids over these prompts carry: repair arms, two-turn
# smokes, fallbacks and outage re-runs. Pass B's own must be none of them.
_PASS_B_TAG = "passb"
_TAKEN_TAGS = frozenset({"res", "bare", "cx", "fb", "r2"})
_SMOKE_TAG = re.compile(r"rs[0-9]*")
_PLANNED_ROLES = (
    "aa_pass_a",
    "aa_pass_b",
    "winner_small",
    "winner_mid",
    "winner_frontier",
)
_SLOTS = ("small", "mid", "frontier")
_STATUSES = frozenset({"registered", "published", "not_run", "unused"})
_ROW_KEYS = frozenset(
    {
        "role",
        "run_id",
        "model_id",
        "slug",
        "quant",
        "reasoning_switch",
        "config",
        "cap_usd",
        "prepare",
        "conditional_on",
        "trigger",
        "status",
        "reason",
        "commit",
    }
)
_SETTINGS = {
    "temperature": 0.0,
    "seed": 17,
    "max_output_tokens": 2048,
    "timeout_seconds": 120.0,
    "json_mode": True,
    "require_parameters": True,
    "allow_fallbacks": False,
    "data_collection": None,
}
# A test pass answers 448 prompts where a dev bake-off pass answered 160.
_TEST_REQUESTS = 448
_DEV_REQUESTS = 160
_CAP_STEP_USD = 0.05
_NOTE_ROW = re.compile(r"\| (\d+) \| `([a-z_]+)` \| .*\|$")
_NOTE_TRIGGER = re.compile(r"(gate stop|outage) of `([^`]+)`")

# Keyed to the results tree, so a deleted registry fails rather than skips.
pytestmark = pytest.mark.skipif(
    not (_ROOT / "docs" / "results").is_dir(), reason=_NO_DOCS
)


def _load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"registry_{name}", _ROOT / "scripts" / f"{name}.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"{name} cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    # The dataclass decorator resolves string annotations through here.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


db = _load("dev_bakeoff")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _runs() -> list[dict[str, Any]]:
    document = _read_json(_REGISTRY)
    assert document["schema"] == "test-runs/1.0"
    runs: list[dict[str, Any]] = document["runs"]
    for run in runs:
        assert set(run) == _ROW_KEYS, run["run_id"]
    return runs


def _slot(role: str) -> str | None:
    """Returns the slot a winner or fallback role serves, else None."""
    for prefix in ("winner_", "fallback_"):
        if role.startswith(prefix):
            return role.removeprefix(prefix)
    return None


def _expected_run_id(run: dict[str, Any]) -> str:
    """Names a run as the bake-off note names its passes, on test."""
    middle = str(run["model_id"]).split("/", 1)[1]
    if run["role"] == "aa_pass_b":
        middle += f"-{_PASS_B_TAG}"
    if str(run["role"]).startswith("fallback_"):
        middle += "-fb"
    if run["trigger"] == "outage":
        middle += "-r2"
    return f"test-{middle}-{_DATE}"


def test_registered_run_ids_follow_the_naming_and_are_unique() -> None:
    """Each id is the bake-off naming on test, unique and a result name."""
    result_dir: re.Pattern[str] = getattr(db.load_model_run(), "_RESULT_DIR")
    runs = _runs()
    ids = [run["run_id"] for run in runs]

    assert len(ids) == len(set(ids))
    assert _PASS_B_TAG not in _TAKEN_TAGS
    assert _SMOKE_TAG.fullmatch(_PASS_B_TAG) is None
    for run in runs:
        assert result_dir.fullmatch(run["run_id"]), run["run_id"]
        assert re.fullmatch(
            r"(dev|test)-[a-z0-9][a-z0-9.-]{0,31}-\d{4}-\d{2}-\d{2}",
            run["run_id"],
        )
        assert run["run_id"] == _expected_run_id(run)


def test_registered_runs_are_the_ruled_winners_and_the_a_a_pair() -> None:
    """The rows are the A/A pair, the ruled winners, fallbacks and re-runs."""
    ruling = _read_json(_RULING)
    runs = _runs()
    by_id = {run["run_id"]: run for run in runs}
    planned = [run for run in runs if run["trigger"] is None]
    anchor = db.ANCHOR.primary.config

    assert [run["role"] for run in planned] == list(_PLANNED_ROLES)
    for run in runs:
        assert run["status"] in _STATUSES
        assert run["reason"] is None or isinstance(run["reason"], str)
        assert run["commit"] is None or isinstance(run["commit"], str)
        slot = _slot(run["role"])
        if slot is None:
            assert run["role"] in ("aa_pass_a", "aa_pass_b")
            assert run["config"].endswith(f"/{anchor}.json")
            assert run["model_id"] == "qwen/qwen3-32b"
            continue
        winner = ruling["slots"][slot]["winner"]
        assert run["model_id"] == ruling["winners"][slot] == winner["model_id"]
        if run["role"] == f"winner_{slot}":
            assert run["config"].endswith(f"/{winner['config']}.json")
            assert run["slug"] == winner["slug"]
            assert run["reasoning_switch"] == winner["reasoning_switch"]
    for run in planned:
        assert run["conditional_on"] is None
        assert run["status"] != "unused"
    # Rule 7: a winner that qualified through its first pass keeps its
    # listed fallback for a gate stop on test; the anchor has none.
    fallbacks = [run for run in runs if run["trigger"] == "gate_stop"]
    for slot in _SLOTS:
        winner = ruling["slots"][slot]["winner"]
        candidate = next(
            c for c in db.PLAN[slot] if c.name == winner["candidate"]
        )
        listed = [run for run in fallbacks if run["role"] == f"fallback_{slot}"]
        if winner["qualified_through"] == "pass" and candidate.fallback:
            assert len(listed) == 1
            assert listed[0]["config"].endswith(
                f"/{candidate.fallback.config}.json"
            )
            primary = by_id[listed[0]["conditional_on"]]
            assert primary["role"] == f"winner_{slot}"
            assert primary["trigger"] is None
        else:
            assert not listed
    for run in runs:
        if run["trigger"] == "gate_stop":
            assert run["role"].startswith("fallback_")
        elif run["trigger"] == "outage":
            repeated = by_id[run["conditional_on"]]
            assert repeated["trigger"] != "outage"
            assert run["run_id"] == repeated["run_id"].replace(
                f"-{_DATE}", f"-r2-{_DATE}"
            )
            for key in ("role", "model_id", "config", "cap_usd", "prepare"):
                assert run[key] == repeated[key], (run["run_id"], key)
        else:
            assert run["trigger"] is None
    repeated_ids = sorted(
        run["conditional_on"] for run in runs if run["trigger"] == "outage"
    )
    assert repeated_ids == sorted(
        run["run_id"] for run in runs if run["trigger"] != "outage"
    )


def test_registered_configs_send_the_listed_route_without_fallbacks() -> None:
    """Each config sends the row's model, slug and switch, nothing else."""
    call_config: Any = getattr(db.load_model_run(), "CallConfigV1")
    document = _read_json(_REGISTRY)
    facts = _read_json(_ROOT / db.EVIDENCE_DIR / "endpoints.json")["configs"]

    assert document["settings"] == _SETTINGS
    assert document["call"] == {
        "gate_first": True,
        "max_attempts": db.MAX_ATTEMPTS,
        "min_interval_seconds": db.MIN_INTERVAL_SECONDS,
    }
    for run in document["runs"]:
        path = _ROOT / run["config"]
        assert path.parent == _ROOT / db.CONFIG_DIR
        config = call_config.model_validate_json(path.read_bytes())
        settings = config.settings.model_dump(mode="json")
        options = settings.pop("openrouter")
        assert settings == {
            "model_id": run["model_id"],
            **{
                key: _SETTINGS[key]
                for key in (
                    "temperature",
                    "seed",
                    "max_output_tokens",
                    "timeout_seconds",
                    "json_mode",
                )
            },
        }
        assert options == {
            "reasoning": run["reasoning_switch"],
            "provider_order": [run["slug"]],
            "allow_fallbacks": False,
            "require_parameters": True,
            "data_collection": None,
        }
        endpoint = facts[path.stem]
        assert endpoint["route"] == run["slug"]
        quantizations = {
            served["quantization"]
            for served in endpoint["endpoints"]
            if served["tag"] in endpoint["provider_endpoint_tags"]
        }
        assert quantizations == {run["quant"]}, path.stem


def test_every_registered_run_answers_the_admitted_test_prompts() -> None:
    """Every row answers the frozen prompt set the freeze record admits."""
    record = held_out.load_record()
    assert record is not None
    runs = _runs()
    receipt = _ROOT / _PREPARE / "prepare.json"

    assert {run["prepare"] for run in runs} == {_PREPARE}
    assert (
        hashlib.sha256(receipt.read_bytes()).hexdigest()
        == record.admitted_prepares[0]
    )
    assert record.prepare.split == "test"
    # The freeze fixed pass A's run id as the prepare id.
    assert runs[0]["role"] == "aa_pass_a"
    assert runs[0]["run_id"] == record.prepare.prepare_id
    assert _PREPARE.endswith(f"/{record.prepare.prepare_id}")
    assert (
        sum(condition.prompt_count for condition in record.prepare.conditions)
        == _TEST_REQUESTS
    )


def _test_prompt_bytes() -> list[int]:
    sizes: list[int] = []
    for label in db.LABELS:
        batch = PreparedBatchV1.model_validate_json(
            (_ROOT / _PREPARE / "prepared" / f"{label}.json").read_bytes()
        )
        sizes.extend(
            sum(len(m.content.encode("utf-8")) for m in prompt.messages)
            for prompt in batch.prompts
        )
    assert len(sizes) == _TEST_REQUESTS
    return sizes


def _dev_spend_usd(dev_run: str, usd_in: float, usd_out: float) -> float:
    """Returns a dev pass's spend, or its tokens at these prices if higher."""
    summary = _read_json(
        _ROOT / "docs" / "results" / dev_run / "scored" / "summary.json"
    )
    spend = summary["spend"]
    recorded = max(
        spend["charged_usd_upper_bound"],
        spend["price_derived_usd"],
        spend["provider_reported_usd"] or 0.0,
    )
    usage = [summary["conditions"][label]["usage"] for label in db.LABELS]
    repriced = (
        sum(u["prompt_tokens"] for u in usage) * usd_in
        + sum(u["completion_tokens"] for u in usage) * usd_out
    ) / db.MICRO
    return max(recorded, repriced)


def test_caps_cover_twice_the_expected_pass_and_one_request() -> None:
    """Each cap is the cap rule's figure, rounded up to the next 0.05 USD."""
    ruling = _read_json(_RULING)
    sizes = _test_prompt_bytes()
    caps: dict[str, float] = {}
    for run in _runs():
        config = _read_json(_ROOT / run["config"])
        usd_in = config["prices"]["usd_per_million_input"]
        usd_out = config["prices"]["usd_per_million_output"]
        slot = _slot(run["role"])
        dev_run = (
            ruling["anchor"]["run_id"]
            if slot is None
            else ruling["slots"][slot]["winner"]["run_id"]
        )
        expected = (
            _dev_spend_usd(dev_run, usd_in, usd_out)
            * _TEST_REQUESTS
            / _DEV_REQUESTS
        )
        worst = (
            max(
                db.worst_case_micro_usd(size, usd_in, usd_out) for size in sizes
            )
            / db.MICRO
        )
        need = 2 * expected + worst
        cap = run["cap_usd"]
        steps = cap / _CAP_STEP_USD

        assert 0 < cap <= db.MAX_USD
        assert math.isclose(steps, round(steps)), run["run_id"]
        assert cap >= need, run["run_id"]
        assert cap - _CAP_STEP_USD < need, run["run_id"]
        caps[run["run_id"]] = cap
    planned = [run["run_id"] for run in _runs() if run["trigger"] is None]
    assert math.isclose(sum(caps[run] for run in planned), 2.35)
    assert math.isclose(sum(caps.values()), 9.0)


def test_the_note_lists_exactly_the_registered_rows() -> None:
    """The binding note and the JSON register the same runs."""
    note = _NOTE.read_text(encoding="utf-8")
    protocol = (_ROOT / "docs" / "protocol.md").read_text(encoding="utf-8")
    listed: list[tuple[str, ...]] = []
    for line in note.splitlines():
        if _NOTE_ROW.fullmatch(line) is None:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        when = cells[9]
        trigger: tuple[str | None, str | None] = (None, None)
        if when != "always":
            match = _NOTE_TRIGGER.fullmatch(when)
            assert match is not None, when
            trigger = (match.group(1).replace(" ", "_"), match.group(2))
        listed.append(
            (
                cells[0],
                *(cell.strip("`") for cell in cells[1:8]),
                cells[8],
                str(trigger[0]),
                str(trigger[1]),
            )
        )
    registered = [
        (
            str(index),
            run["role"],
            run["run_id"],
            run["model_id"],
            run["slug"],
            run["quant"],
            run["reasoning_switch"],
            Path(run["config"]).stem,
            f"{run['cap_usd']:.2f}",
            str(run["trigger"]),
            str(run["conditional_on"]),
        )
        for index, run in enumerate(_runs(), start=1)
    ]

    assert listed == registered
    assert f"`{_PREPARE}`" in note
    assert "(decisions/test-runs.md)" in protocol
