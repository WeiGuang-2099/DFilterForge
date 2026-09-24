"""Reading a stored run directory and writing its scored tree.

Everything that knows the layout of a run directory lives here: the bounded
file reader, the manifest, split and prompt cross-checks, the routing of
committed items onto gold cases, the derivation of what the endpoint
actually served and of what the run cost, the aggregation into a summary,
and the deterministic render, write and byte-for-byte comparison of
``scored``.

The verdict engine in :mod:`dfilterforge.scoring` imports this module and
nothing here imports it back, so the two halves stay separable. Nothing in
this module contacts a network or executes tshark.
"""

# The run-directory helpers thread run identity through every function.
# pylint: disable=too-many-arguments,too-many-positional-arguments

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from datetime import timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import shutil
import stat
from typing import cast, NamedTuple, TypeAlias, TypeVar

from pydantic import ValidationError

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.completions import CompletionBatchV1
from dfilterforge.completions import CompletionStatusV1
from dfilterforge.completions import CompletionV1
from dfilterforge.completions import PrepareManifestV1
from dfilterforge.completions import RunManifestV1
from dfilterforge.completions import thinking_state
from dfilterforge.errors import DFilterForgeError
from dfilterforge.generation import condition_label
from dfilterforge.generation import GenerationInputV1
from dfilterforge.generation import OutputContractV1
from dfilterforge.generation import prepare_batch
from dfilterforge.generation import PreparedBatchV1
from dfilterforge.generation import PreparedPromptV1
from dfilterforge.generation import prompt_versions
from dfilterforge.generation import RetrievalV1
from dfilterforge.intent_ir import FrozenModel
from dfilterforge.live import LiveEnvironmentV1
from dfilterforge.model_split import ModelGoldCaseV1
from dfilterforge.model_split import ModelGoldV1
from dfilterforge.model_split import ModelInputItemV1
from dfilterforge.score_report import render_markdown
from dfilterforge.score_summary import CONDITION_ORDER
from dfilterforge.score_summary import ConditionLabel
from dfilterforge.score_summary import derived_cost
from dfilterforge.score_summary import EffectiveSettingsV1
from dfilterforge.score_summary import ItemOutcomeV1
from dfilterforge.score_summary import MAX_EFFECTIVE_VALUES
from dfilterforge.score_summary import ScoreSummaryV1
from dfilterforge.score_summary import SpendV1
from dfilterforge.score_summary import summarize
from dfilterforge.score_summary import token_census

ModelT = TypeVar("ModelT", bound=FrozenModel)

PreparedFiles: TypeAlias = Mapping[ConditionLabel, tuple[PreparedBatchV1, str]]

SCORED_NAME = "scored"
MANIFEST_NAME = "run_manifest.json"
PREPARE_NAME = "prepare.json"
SCORE_MANIFEST_NAME = "score_manifest.json"
MAX_RUN_FILE_BYTES = 32 * 1024 * 1024
_TREES = ("intents", "receipts", "specs")
_RECEIPTS = "receipts"
_OUTCOMES_NAME = "outcomes.jsonl"
_CONDITIONS: dict[ConditionLabel, tuple[OutputContractV1, RetrievalV1]] = {
    condition_label(contract, retrieval): (contract, retrieval)
    for contract, retrieval in itertools.product(OutputContractV1, RetrievalV1)
}


class ScoringError(DFilterForgeError, RuntimeError):
    """A sanitized offline scoring failure with a stable public code.

    The codes are ``run_layout_invalid``, ``condition_mismatch``,
    ``items_mismatch``, ``model_mismatch``, ``split_violation``,
    ``prompt_mismatch``, ``manifest_mismatch``, ``gold_invalid`` and
    ``item_aborted``. Every message is built only from a condition label,
    an item id, a case id, a file name and an error code: no model text, no
    captured stderr and no absolute path.
    """


def _read_run_file(
    path: Path,
    model_type: type[ModelT],
    *,
    max_bytes: int = MAX_RUN_FILE_BYTES,
) -> tuple[ModelT, str]:
    """Reads one bounded regular run file and hashes the bytes it validated.

    A symlink, a directory, an oversized file, undecodable bytes and a
    contract violation all raise ``run_layout_invalid``, and this is the
    only function in the package that opens a run file. Returning the digest
    beside the contract is what lets the manifest cross-check avoid a
    second read.
    """
    try:
        status = os.lstat(path)
        if not stat.S_ISREG(status.st_mode) or status.st_size > max_bytes:
            raise OSError("run file is not a bounded regular file")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise OSError("run file exceeds its byte limit")
        model = model_type.model_validate_json(raw.decode("utf-8"))
        return model, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, ValidationError):
        raise ScoringError(
            "run_layout_invalid", f"{path.name} is not a readable run file"
        ) from None


def _prepared_paths(run_dir: Path) -> dict[ConditionLabel, Path]:
    """Enumerates ``prepared/`` and refuses anything that is not a condition.

    Probing four fixed names would drop a dangling symlink silently,
    because :meth:`Path.exists` reports a broken link as absent; listing
    the directory instead makes every entry either a named condition file
    that :func:`_read_run_file` validates or a refusal.
    """
    try:
        entries = sorted(path.name for path in (run_dir / "prepared").iterdir())
    except OSError:
        raise ScoringError(
            "run_layout_invalid", "prepared is not a readable directory"
        ) from None
    names: dict[str, ConditionLabel] = {
        f"{label}.json": label for label in CONDITION_ORDER
    }
    found: dict[ConditionLabel, Path] = {}
    for name in entries:
        label = names.get(name)
        if label is None:
            raise ScoringError(
                "run_layout_invalid",
                "prepared holds a file that is not a condition file",
            )
        found[label] = run_dir / "prepared" / name
    if not found:
        raise ScoringError(
            "run_layout_invalid", "prepared holds no condition file"
        )
    return {label: found[label] for label in CONDITION_ORDER if label in found}


def _load_completions(
    run_dir: Path, prepared: PreparedFiles
) -> dict[ConditionLabel, CompletionBatchV1]:
    """Reads one completion batch per prepared condition and cross-checks it."""
    completions: dict[ConditionLabel, CompletionBatchV1] = {}
    model_ids: set[str] = set()
    for label, (batch, _) in prepared.items():
        path = run_dir / "completions" / f"{label}.json"
        if not os.path.lexists(path):
            raise ScoringError(
                "run_layout_invalid", f"completions/{label}.json is missing"
            )
        recorded, _ = _read_run_file(path, CompletionBatchV1)
        if (recorded.output_contract, recorded.retrieval) != (
            batch.output_contract,
            batch.retrieval,
        ):
            raise ScoringError(
                "condition_mismatch",
                f"{label}: completions are not this condition",
            )
        if {item.item_id for item in recorded.completions} != {
            prompt.item_id for prompt in batch.prompts
        }:
            raise ScoringError(
                "items_mismatch", f"{label}: completions do not cover prompts"
            )
        model_ids.add(recorded.settings.model_id)
        completions[label] = recorded
    if len(model_ids) > 1:
        raise ScoringError(
            "model_mismatch", "completion batches record different models"
        )
    return completions


class LoadedRun(NamedTuple):
    """Everything one run directory committed, validated and digested."""

    manifest: RunManifestV1 | None
    prepare: PrepareManifestV1 | None
    prepared: dict[ConditionLabel, tuple[PreparedBatchV1, str]]
    completions: dict[ConditionLabel, CompletionBatchV1]


def load_run(run_dir: Path, *, with_completions: bool = True) -> LoadedRun:
    """Reads a run directory into validated, digest-carrying contracts.

    A published directory carries ``prepare.json`` beside ``prepared/``
    from the moment the prompts are frozen, and it is read here whether or
    not a run manifest exists: it is the only provenance a control pass
    taken before any paid request can have, and its split is the type that
    keeps a held-out item out of a published tree.

    Args:
        run_dir: The run directory to read.
        with_completions: Whether to read ``completions/``. A pass that
            answers the committed prompts from gold never reads that
            directory, so its absence is not a layout failure there.

    Returns:
        The optional run manifest, the optional standalone prepare
        manifest, the prepared batches with the digest of the bytes each
        was validated from, and the completion batches, which are empty
        when they were not read.

    Raises:
        ScoringError: For any layout or contract failure.
    """
    if not run_dir.is_dir():
        raise ScoringError(
            "run_layout_invalid", f"{run_dir.name} is not a run directory"
        )
    manifest: RunManifestV1 | None = None
    manifest_path = run_dir / MANIFEST_NAME
    if os.path.lexists(manifest_path):
        manifest, _ = _read_run_file(manifest_path, RunManifestV1)
    prepare: PrepareManifestV1 | None = None
    prepare_path = run_dir / PREPARE_NAME
    if os.path.lexists(prepare_path):
        prepare, _ = _read_run_file(prepare_path, PrepareManifestV1)
    prepared: dict[ConditionLabel, tuple[PreparedBatchV1, str]] = {}
    for label, path in _prepared_paths(run_dir).items():
        batch, digest = _read_run_file(path, PreparedBatchV1)
        if condition_label(batch.output_contract, batch.retrieval) != label:
            raise ScoringError(
                "condition_mismatch",
                f"{label}: prepared batch is not this condition",
            )
        prepared[label] = (batch, digest)
    if not with_completions:
        return LoadedRun(manifest, prepare, prepared, {})
    return LoadedRun(
        manifest, prepare, prepared, _load_completions(run_dir, prepared)
    )


def check_prepare(prepare: PrepareManifestV1, prepared: PreparedFiles) -> None:
    """Requires the prepare manifest to describe the committed prompts.

    The check runs in both directions. A manifest that declares a condition
    whose prompt file was never committed would otherwise let a whole
    condition disappear from a published summary with no signal at all. The
    per-condition digest is the one that proves the committed prompt file is
    byte for byte the file whose hash was recorded before any request.

    Raises:
        ScoringError: With code ``manifest_mismatch`` naming the first
            condition that the manifest does not describe.
    """
    described = {condition.label: condition for condition in prepare.conditions}
    undescribed = sorted(set(described) ^ set(prepared))
    if undescribed:
        raise ScoringError(
            "manifest_mismatch",
            f"{undescribed[0]}: manifest and committed prompts disagree",
        )
    declared = set(prepare.item_ids)
    for label, (batch, digest) in prepared.items():
        condition = described[label]
        committed = {prompt.item_id for prompt in batch.prompts}
        if (
            condition.sha256 != digest
            or condition.prompt_count != len(batch.prompts)
            or (condition.output_contract, condition.retrieval)
            != (batch.output_contract, batch.retrieval)
            or not committed <= declared
        ):
            raise ScoringError(
                "manifest_mismatch",
                f"{label}: manifest does not describe the committed prompts",
            )


def check_manifest(
    manifest: RunManifestV1,
    prepared: PreparedFiles,
    completions: Mapping[ConditionLabel, CompletionBatchV1],
) -> None:
    """Requires the manifest to describe exactly the committed prompts.

    The embedded prepare manifest is checked by :func:`check_prepare`, and
    the per-condition attempt census is checked against it here.

    The manifest's request settings are checked against the settings
    recorded on every completion batch as well. The summary reports the
    requested half of its provenance from the manifest and the served
    half from the batches, so a manifest that names another model, or
    another temperature, than the one the client sent would publish two
    different runs as one. That cross-check has no subject when the caller
    read no completions, which is the case for a pass that answers the
    committed prompts from gold: such a pass records no settings claim of
    its own, and the manifest's is left untested rather than confirmed.
    """
    for label, batch in completions.items():
        if batch.settings != manifest.settings:
            raise ScoringError(
                "manifest_mismatch",
                f"{label}: manifest settings are not the recorded ones",
            )
    check_prepare(manifest.prepare, prepared)
    census = {condition.label: condition for condition in manifest.conditions}
    undescribed = sorted(set(census) ^ set(prepared))
    if undescribed:
        raise ScoringError(
            "manifest_mismatch",
            f"{undescribed[0]}: manifest and committed prompts disagree",
        )
    for label, (batch, _) in prepared.items():
        run = census[label]
        if run.completed + run.failed + run.pending != len(batch.prompts):
            raise ScoringError(
                "manifest_mismatch",
                f"{label}: manifest does not describe the committed prompts",
            )


def check_splits(
    prepared: PreparedFiles,
    manifest: RunManifestV1 | None,
    prepare: PrepareManifestV1 | None = None,
) -> str:
    """Requires one non-null split shared by every prompt and the manifest.

    Either manifest pins the split, and the embedded one wins when both
    are committed, because the run manifest is the file that names the
    prepare manifest it was built from.
    """
    splits = {
        prompt.split
        for batch, _ in prepared.values()
        for prompt in batch.prompts
    }
    if len(splits) != 1 or None in splits:
        raise ScoringError(
            "split_violation", "prepared prompts do not share one split"
        )
    split = splits.pop()
    assert split is not None
    pinned = manifest.prepare if manifest is not None else prepare
    if pinned is not None and split != pinned.split:
        raise ScoringError(
            "split_violation", "prompts and manifest disagree on the split"
        )
    return split


def selected_cases(
    prompts: Sequence[PreparedPromptV1], gold: ModelGoldV1, split: str
) -> tuple[dict[str, ModelGoldCaseV1], tuple[ModelGoldCaseV1, ...]]:
    """Routes every item to a gold case of the prompts' own split.

    The returned tuple preserves ``gold.cases`` order, and that order is
    exactly what the published ``gold_hash`` hashes. Sorting it differently,
    by case id or otherwise, silently rewrites the hash in every committed
    summary, so the order is part of the contract rather than an accident.
    """
    by_case = {case.case_id: case for case in gold.cases}
    routes: dict[str, ModelGoldCaseV1] = {}
    for prompt in prompts:
        case_id = gold.item_to_case.get(prompt.item_id)
        case = None if case_id is None else by_case.get(case_id)
        if case is None or case.spec.split != split:
            raise ScoringError(
                "split_violation",
                f"{prompt.item_id} does not route to a {split} case",
            )
        routes[prompt.item_id] = case
    chosen = {case.case_id for case in routes.values()}
    return routes, tuple(case for case in gold.cases if case.case_id in chosen)


def check_prompts(
    prepared: PreparedFiles, items_by_id: Mapping[str, ModelInputItemV1]
) -> None:
    """Re-prepares every committed prompt and requires an exact match.

    A condition's prompts are rebuilt under each system prompt version,
    newest first, and must all match under one of them, so a run prepared
    before a prompt change still re-scores while a batch mixing versions,
    or a prompt no version reproduces, is refused.
    """
    for label, (batch, _) in prepared.items():
        output_contract, retrieval = _CONDITIONS[label]
        versions = range(prompt_versions(output_contract), 0, -1)
        mismatches = [
            [
                prompt.item_id
                for prompt in batch.prompts
                if _rebuilt(prompt, items_by_id, retrieval, version) != prompt
            ]
            for version in versions
        ]
        if all(mismatches):
            raise ScoringError("prompt_mismatch", f"{label} {mismatches[0][0]}")


def _rebuilt(
    prompt: PreparedPromptV1,
    items_by_id: Mapping[str, ModelInputItemV1],
    retrieval: RetrievalV1,
    version: int,
) -> PreparedPromptV1:
    """Prepares one committed prompt's item again under one prompt version."""
    item = items_by_id[prompt.item_id]
    return prepare_batch(
        [
            GenerationInputV1(
                item_id=item.item_id,
                intent=item.intent,
                user_assumptions=item.user_assumptions,
                retrieved_fields=(
                    prompt.retrieved_fields
                    if retrieval is RetrievalV1.LEXICAL
                    else None
                ),
                split=item.split,
            )
        ],
        output_contract=prompt.output_contract,
        retrieval=retrieval,
        prompt_version=version,
    ).prompts[0]


class _Served(NamedTuple):
    """The provider-chosen values of one run, truncated and counted."""

    models: tuple[str, ...]
    models_distinct: int
    model_changed: bool
    providers: tuple[str, ...]
    providers_distinct: int
    provider_changed: bool
    fingerprints: tuple[str, ...]
    fingerprints_distinct: int


def _distinct(values: Iterable[str | None]) -> tuple[tuple[str, ...], int]:
    """Truncates the distinct recorded values and counts them first.

    The count is published beside the list, so a run whose router
    answered with more values than the report prints says how many there
    were instead of reading like a run that answered with eight.
    """
    seen = sorted({value for value in values if value is not None})
    return tuple(seen[:MAX_EFFECTIVE_VALUES]), len(seen)


def _provider_key(name: str) -> str:
    """Reduces a provider route slug or display name to one comparable key.

    OpenRouter routes by lowercase slug (``deepinfra``, or ``deepinfra/fp8``
    for one endpoint) but names the provider that answered by its display
    name (``DeepInfra``). Both reduce to the slug's first path segment,
    case-folded, with every character that is not a letter or a digit
    dropped, so a reply from the pinned provider is not read as a change.
    """
    return re.sub(r"[^0-9a-z]", "", name.split("/", 1)[0].casefold())


def _served(
    answered: Sequence[CompletionV1], requested: str, pinned: Sequence[str]
) -> _Served:
    """Collects what the provider served and whether it is what was asked.

    A changed flag answers the question its name asks: whether the run
    was served something other than what it requested. One consistently
    substituted model id therefore reads as changed, and so does a
    provider outside a pinned route list, neither of which varies within
    the run. Served providers are matched to pinned routes by
    :func:`_provider_key`, because the two are spelled differently.
    """
    models, models_count = _distinct(
        record.response_model for record in answered
    )
    providers, providers_count = _distinct(
        record.provider for record in answered
    )
    fingerprints, fingerprints_count = _distinct(
        record.system_fingerprint for record in answered
    )
    return _Served(
        models=models,
        models_distinct=models_count,
        model_changed=bool(models) and set(models) != {requested},
        providers=providers,
        providers_distinct=providers_count,
        provider_changed=bool(providers)
        and (
            providers_count > 1
            or (
                bool(pinned)
                and not {_provider_key(name) for name in providers}
                <= {_provider_key(route) for route in pinned}
            )
        ),
        fingerprints=fingerprints,
        fingerprints_distinct=fingerprints_count,
    )


def effective_settings(
    batches: Sequence[CompletionBatchV1], manifest: RunManifestV1
) -> EffectiveSettingsV1:
    """Reports what the endpoint served beside what the run requested.

    Args:
        batches: Every recorded completion batch of the run.
        manifest: The run manifest holding the requested settings.

    Returns:
        The effective settings, with every served value collected from
        the records the provider answered and nothing else.
    """
    answered = [
        record
        for batch in batches
        for record in batch.completions
        if record.status is CompletionStatusV1.COMPLETED
    ]
    settings = manifest.settings
    options = settings.openrouter
    pinned = () if options is None else options.provider_order
    served = _served(answered, settings.model_id, pinned)
    thinking, evidence = thinking_state(answered)
    return EffectiveSettingsV1(
        requested_model=settings.model_id,
        served_models=served.models,
        served_models_distinct=served.models_distinct,
        served_model_changed=served.model_changed,
        providers=served.providers,
        providers_distinct=served.providers_distinct,
        provider_changed=served.provider_changed,
        system_fingerprints=served.fingerprints,
        system_fingerprints_distinct=served.fingerprints_distinct,
        reasoning_tokens_total=sum(
            record.reasoning_tokens or 0 for record in answered
        ),
        items_with_reasoning=sum(
            1
            for record in answered
            if (record.reasoning_tokens or 0) > 0 or record.reasoning_present
        ),
        thinking=thinking,
        thinking_evidence_items=evidence,
        seed_requested=settings.seed,
        temperature=settings.temperature,
        max_output_tokens=settings.max_output_tokens,
        json_mode=settings.json_mode,
        provider_order=tuple(pinned),
        allow_fallbacks=None if options is None else options.allow_fallbacks,
        timeout_seconds=settings.timeout_seconds,
    )


def _prices(manifest: RunManifestV1 | None) -> tuple[float, float] | None:
    """Returns the recorded token prices, or None when none were recorded."""
    if manifest is None or manifest.prices is None:
        return None
    return (
        manifest.prices.usd_per_million_input,
        manifest.prices.usd_per_million_output,
    )


def _retried_items(manifest: RunManifestV1) -> int:
    """Counts the item attempts the run recorded more than once.

    Only the last attempt of a retried item leaves a completion record,
    so its earlier attempts are absent from every token census the
    scorer can take. The manifest counted them, which is the only place
    the derived figure can learn that it is short.
    """
    return sum(
        1
        for condition in manifest.conditions
        for count in condition.attempts.values()
        if count > 1
    )


def reconciled_spend(
    outcomes: Sequence[ItemOutcomeV1], manifest: RunManifestV1
) -> SpendV1:
    """Puts the derived cost beside what the provider said it charged.

    Args:
        outcomes: Every scored item of the run, in any order.
        manifest: The run manifest holding the prices, the charges and
            the per-item attempt census.

    Returns:
        The reconciled spend, whose derived figure is absent when no
        prices were recorded, a lower bound when usage was missing or an
        item was retried, and flagged when it exceeds the recorded
        charge.
    """
    prompt_tokens, completion_tokens, missing = token_census(outcomes)
    derived = derived_cost(prompt_tokens, completion_tokens, _prices(manifest))
    retried = _retried_items(manifest)
    charged = manifest.charged_usd_upper_bound
    return SpendV1(
        price_derived_usd=derived,
        price_derived_is_lower_bound=(
            derived is not None and (missing > 0 or retried > 0)
        ),
        usage_missing=missing,
        retried_items=retried,
        provider_reported_usd=manifest.provider_reported_usd,
        charged_usd_upper_bound=charged,
        derived_above_charged=derived is not None and derived > charged,
    )


def summarize_run(
    outcomes: Sequence[ItemOutcomeV1],
    prepared: PreparedFiles,
    completions: Mapping[ConditionLabel, CompletionBatchV1],
    selected: Sequence[ModelGoldCaseV1],
    manifest: RunManifestV1 | None,
    *,
    run: str,
    split: str,
    synthesized: bool = False,
    not_measured: Mapping[str, str] | None = None,
) -> ScoreSummaryV1:
    """Aggregates the scored items with the run's recorded provenance.

    Args:
        outcomes: Every scored item of the run.
        prepared: The committed conditions that were scored.
        completions: The answers those conditions were scored against.
        selected: The gold cases the items routed to.
        manifest: The run manifest, or None when the run recorded none.
        run: The run identifier recorded beside the numbers.
        split: The evaluation split the items came from.
        synthesized: Whether the answers were derived rather than read
            from the run directory. A derived batch is no committed file,
            so its hash would name nothing and is left out.
        not_measured: Extra skipped metrics merged over the defaults.

    Returns:
        The frozen summary for the whole run.
    """
    batch_hashes = {
        f"prepared/{label}": content_sha256(batch)
        for label, (batch, _) in prepared.items()
    }
    if not synthesized:
        batch_hashes.update(
            {
                f"completions/{label}": content_sha256(batch)
                for label, batch in completions.items()
            }
        )
    return summarize(
        outcomes,
        run=run,
        model_id=next(iter(completions.values())).settings.model_id,
        split=split,
        gold_hash=content_sha256(tuple(selected)),
        capture_hashes={
            probe.probe_id: probe.capture_sha256
            for case in selected
            for probe in case.spec.probes
        },
        batch_hashes=batch_hashes,
        usd_per_million_tokens=_prices(manifest),
        provider_reported_usd=(
            None if manifest is None else manifest.provider_reported_usd
        ),
        charged_usd_upper_bound=(
            None if manifest is None else manifest.charged_usd_upper_bound
        ),
        effective_settings=(
            None
            if manifest is None
            else effective_settings(tuple(completions.values()), manifest)
        ),
        spend=(
            None if manifest is None else reconciled_spend(outcomes, manifest)
        ),
        not_measured=not_measured,
    )


def _encode(value: object) -> bytes:
    """Encodes one committed artifact as canonical JSON plus a newline."""
    return (canonical_json(value) + "\n").encode("utf-8")


def render(
    summary: ScoreSummaryV1,
    outcomes: Sequence[ItemOutcomeV1],
    files: Mapping[str, FrozenModel],
    selected: Sequence[ModelGoldCaseV1],
    *,
    code_revision: str,
    environment: LiveEnvironmentV1,
) -> dict[str, bytes]:
    """Renders the whole scored tree in memory before anything is written."""
    rendered = {name: _encode(model) for name, model in files.items()}
    for case in selected:
        rendered[f"specs/{case.case_id}.json"] = _encode(case.spec)
    ordered = sorted(outcomes, key=lambda item: (item.condition, item.item_id))
    rendered[_OUTCOMES_NAME] = "".join(
        canonical_json(outcome) + "\n" for outcome in ordered
    ).encode("utf-8")
    rendered["summary.json"] = _encode(summary)
    rendered["summary.md"] = render_markdown(summary).encode("utf-8")
    rendered[SCORE_MANIFEST_NAME] = _encode(
        {
            "schema_version": "score-manifest/1.0",
            "code_revision": code_revision,
            "scored_at": datetime.now(timezone.utc).isoformat(),
            "environment": environment,
            "environment_hash": environment.environment_hash(),
        }
    )
    return rendered


def write_scored(
    run_dir: Path, rendered: Mapping[str, bytes], *, name: str = SCORED_NAME
) -> Path:
    """Stages the whole tree, then swaps it in, so no torn state survives.

    Args:
        run_dir: The run directory to write inside.
        rendered: The whole tree, already rendered in memory.
        name: The directory to write, which a control pass points at its
            own tree so that two passes over one run never disturb each
            other's committed bytes.

    Returns:
        The directory that was written.
    """
    target = run_dir / name
    staging = run_dir / f".{name}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    for relative, payload in rendered.items():
        path = staging / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    shutil.rmtree(target, ignore_errors=True)
    os.replace(staging, target)
    return target


def _read_bytes(path: Path) -> bytes | None:
    """Returns a committed file's bytes, or None when it cannot be read."""
    try:
        return path.read_bytes()
    except OSError:
        return None


def _outcome_lines(payload: bytes) -> dict[str, bytes]:
    """Keys committed outcome lines by condition and item id.

    The line bytes are kept as they were read, so a line is compared
    exactly; a line that no longer validates keeps its position as its key
    and therefore still reports as a difference. Ordering and duplication
    are deliberately invisible here and are caught by the whole-file byte
    comparison in :func:`compare`.
    """
    lines: dict[str, bytes] = {}
    for index, line in enumerate(payload.split(b"\n")):
        if not line:
            continue
        try:
            item = ItemOutcomeV1.model_validate_json(line)
            key = f"{item.condition}/{item.item_id}"
        except ValidationError:
            key = f"line-{index + 1}"
        lines[key] = line
    return lines


def _comparable_receipt(payload: bytes) -> bytes | str:
    """Drops the timestamp, the revision and the three runtime fields.

    A committed receipt that no longer parses is returned as its own raw
    bytes, which can never equal the canonical JSON of a rendered one, so
    an unreadable file is always a difference rather than a match.
    """
    try:
        document: object = json.loads(payload.decode("utf-8"))
    except (UnicodeError, ValueError):
        return payload
    if not isinstance(document, dict):
        return payload
    receipt = cast("dict[str, object]", document)
    for key in ("created_at", "code_revision"):
        receipt.pop(key, None)
    metrics = receipt.get("metrics")
    if isinstance(metrics, dict):
        for key in ("p50_runtime_ms", "p95_runtime_ms"):
            cast("dict[str, object]", metrics).pop(key, None)
    probes = receipt.get("probes")
    if isinstance(probes, list):
        for probe in cast("list[object]", probes):
            if isinstance(probe, dict):
                cast("dict[str, object]", probe).pop("runtime_ms", None)
    return canonical_json(receipt)


def _comparable(prefix: str, payload: bytes) -> bytes | str:
    """Normalizes one committed file of a compared tree.

    Only a receipt is normalized; an intent and a specification carry no
    timestamp and no runtime, so their bytes are compared as they stand.
    """
    if prefix != _RECEIPTS:
        return payload
    return _comparable_receipt(payload)


def _compare_tree(
    target: Path, rendered: Mapping[str, bytes], prefix: str
) -> set[str]:
    """Compares one committed subtree, including files only found on disk.

    Presence is tested before any normalization, so a committed file that
    the scorer no longer produces and that no longer parses cannot collapse
    into the same value as an absent one.
    """
    names = {name for name in rendered if name.startswith(f"{prefix}/")}
    base = target / prefix
    if base.is_dir():
        names.update(
            path.relative_to(target).as_posix()
            for path in base.rglob("*.json")
            if path.is_file()
        )
    differences: set[str] = set()
    for name in names:
        stem = name[len(prefix) + 1 :].removesuffix(".json")
        expected = rendered.get(name)
        actual = _read_bytes(target / name)
        if expected is None or actual is None:
            differences.add(f"{prefix}:{stem}")
        elif _comparable(prefix, expected) != _comparable(prefix, actual):
            differences.add(f"{prefix}:{stem}")
    return differences


def compare(target: Path, rendered: Mapping[str, bytes]) -> tuple[str, ...]:
    """Names every committed file that differs, without touching the tree."""
    committed = _read_bytes(target / _OUTCOMES_NAME)
    expected = _outcome_lines(rendered[_OUTCOMES_NAME])
    actual = _outcome_lines(committed or b"")
    differences = {
        f"outcomes:{key}"
        for key in set(expected) | set(actual)
        if expected.get(key) != actual.get(key)
    }
    if not differences and committed != rendered[_OUTCOMES_NAME]:
        differences.add(_OUTCOMES_NAME)
    for name in ("summary.json", "summary.md"):
        if _read_bytes(target / name) != rendered[name]:
            differences.add(name)
    for prefix in _TREES:
        differences.update(_compare_tree(target, rendered, prefix))
    return tuple(sorted(differences))
