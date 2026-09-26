"""Writes one call configuration per bake-off (model, provider) pair.

Run from the repository root:

    uv run --frozen python scripts/dev_bakeoff_configs.py [--force]

Each endpoint is read from OpenRouter's keyless model metadata; no
credential is read or sent. The slug sent follows the bake-off note: the
provider's base slug when it serves exactly one endpoint of the model,
the full endpoint tag when it serves more than one, and the base slug
``mistral`` for both Mistral models by decision. That slug matches the
``mistral``, ``mistral/zdr`` and ``mistral/eu`` endpoints of the same
weights, the served variant is not recorded, and the highest of their
prices is recorded.

The recorded price is the listed price at the fetch, which is what
OpenRouter bills. A listed discount is named in the price source, because
the call step's pre-request bound stops being an upper bound if the
discount ends during a run.

Every ``RequestSettingsV1`` and ``OpenRouterOptionsV1`` field is written
out, and every file is validated with ``CallConfigV1`` before it is
written. A configuration that already exists is never changed without
``--force``, because a resumed run refuses a configuration whose settings
or prices differ from its manifest.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, cast
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = "docs/decisions/evidence/bakeoff"
CONFIG_DIR = f"{EVIDENCE_DIR}/configs"
ENDPOINTS_FILE = f"{EVIDENCE_DIR}/endpoints.json"
ENDPOINT_URL = "https://openrouter.ai/api/v1/chat/completions"
_METADATA_URL = "https://openrouter.ai/api/v1/models/{model}/endpoints"
_MAX_METADATA_BYTES = 4 << 20
MAX_OUTPUT_TOKENS = 2048
# The body keys every request sends; OpenRouter routes only to endpoints
# that support all of them because require_parameters is true.
SENT_PARAMETERS = ("temperature", "max_tokens", "seed", "response_format")
# Pricing keys the pre-request bound can ignore: cached-input reads only
# lower a bill, and a discount is already applied to the listed price.
_IGNORED_PRICING = frozenset(
    {
        "prompt",
        "completion",
        "input_cache_read",
        "input_cache_write",
        "discount",
    }
)
_ENDPOINT_FACTS = (
    "tag",
    "provider_name",
    "quantization",
    "status",
    "uptime_last_30m",
    "uptime_last_1d",
    "context_length",
    "max_completion_tokens",
    "pricing",
    "supported_parameters",
)


@dataclass(frozen=True)
class ConfigSpec:
    """One (model, slug, reasoning switch) configuration.

    ``spans_endpoints`` marks a base slug that is sent although the
    provider serves several endpoints of the model; only the Mistral rows
    carry it, by decision.
    """

    name: str
    model_id: str
    route: str
    reasoning: str | None
    spans_endpoints: bool = False


SPECS: tuple[ConfigSpec, ...] = (
    ConfigSpec(
        "qwen3-32b_deepinfra_enabled-false",
        "qwen/qwen3-32b",
        "deepinfra",
        "enabled_false",
    ),
    ConfigSpec(
        "qwen3.5-9b_deepinfra_enabled-false",
        "qwen/qwen3.5-9b",
        "deepinfra",
        "enabled_false",
    ),
    ConfigSpec(
        "qwen3.5-9b_parasail_enabled-false",
        "qwen/qwen3.5-9b",
        "parasail",
        "enabled_false",
    ),
    ConfigSpec(
        "ministral-8b-2512_mistral_none",
        "mistralai/ministral-8b-2512",
        "mistral",
        None,
        spans_endpoints=True,
    ),
    ConfigSpec(
        "granite-4.2-8b_deepinfra_enabled-false",
        "ibm-granite/granite-4.2-8b",
        "deepinfra",
        "enabled_false",
    ),
    ConfigSpec(
        "granite-4.2-8b_coreweave_enabled-false",
        "ibm-granite/granite-4.2-8b",
        "coreweave",
        "enabled_false",
    ),
    ConfigSpec(
        "llama-3.1-8b-instruct_deepinfra_none",
        "meta-llama/llama-3.1-8b-instruct",
        "deepinfra",
        None,
    ),
    ConfigSpec(
        "qwen3.5-122b-a10b_novita_enabled-false",
        "qwen/qwen3.5-122b-a10b",
        "novita",
        "enabled_false",
    ),
    ConfigSpec(
        "qwen3.5-122b-a10b_atlas-cloud_enabled-false",
        "qwen/qwen3.5-122b-a10b",
        "atlas-cloud",
        "enabled_false",
    ),
    ConfigSpec(
        "mistral-medium-3-5_mistral_effort-none",
        "mistralai/mistral-medium-3-5",
        "mistral",
        "effort_none",
        spans_endpoints=True,
    ),
    ConfigSpec(
        "mistral-medium-3-5_mistral_enabled-false",
        "mistralai/mistral-medium-3-5",
        "mistral",
        "enabled_false",
        spans_endpoints=True,
    ),
    ConfigSpec(
        "nemotron-3-super-120b-a12b_deepinfra_enabled-false",
        "nvidia/nemotron-3-super-120b-a12b",
        "deepinfra",
        "enabled_false",
    ),
    ConfigSpec(
        "nemotron-3-super-120b-a12b_dekallm_enabled-false",
        "nvidia/nemotron-3-super-120b-a12b",
        "dekallm",
        "enabled_false",
    ),
    ConfigSpec(
        "qwen3-next-80b-a3b-instruct_alibaba_none",
        "qwen/qwen3-next-80b-a3b-instruct",
        "alibaba",
        None,
    ),
    ConfigSpec(
        "deepseek-v4-pro-0813_deepinfra_enabled-false",
        "deepseek/deepseek-v4-pro-0813",
        "deepinfra",
        "enabled_false",
    ),
    ConfigSpec(
        "deepseek-v4-pro-0813_nextbit_enabled-false",
        "deepseek/deepseek-v4-pro-0813",
        "nextbit",
        "enabled_false",
    ),
    ConfigSpec(
        "glm-5.2_alibaba-fp8_enabled-false",
        "z-ai/glm-5.2",
        "alibaba/fp8",
        "enabled_false",
    ),
    ConfigSpec(
        "glm-5.2_novita_enabled-false",
        "z-ai/glm-5.2",
        "novita",
        "enabled_false",
    ),
    ConfigSpec(
        "kimi-k2.6_parasail_enabled-false",
        "moonshotai/kimi-k2.6",
        "parasail",
        "enabled_false",
    ),
    ConfigSpec(
        "kimi-k2.6_inceptron_enabled-false",
        "moonshotai/kimi-k2.6",
        "inceptron",
        "enabled_false",
    ),
    ConfigSpec(
        "kimi-k2-0905_novita_none",
        "moonshotai/kimi-k2-0905",
        "novita",
        None,
    ),
)


class ConfigError(RuntimeError):
    """An endpoint cannot carry the requests the bake-off sends."""


def load_model_run() -> ModuleType:
    """Loads scripts/model_run.py for its public call contract.

    Raises:
        ConfigError: If the script cannot be loaded.
    """
    path = ROOT / "scripts" / "model_run.py"
    spec = importlib.util.spec_from_file_location("bakeoff_model_run", path)
    if spec is None or spec.loader is None:
        raise ConfigError("scripts/model_run.py cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def fetch_endpoints(model_id: str) -> dict[str, Any]:
    """Reads one model's endpoint list without any credential.

    Args:
        model_id: The OpenRouter model slug.

    Returns:
        The ``data`` object of the endpoints reply.

    Raises:
        ConfigError: If the reply is oversized or has no endpoint list.
    """
    request = urllib.request.Request(
        _METADATA_URL.format(model=model_id),
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as reply:
        body = reply.read(_MAX_METADATA_BYTES + 1)
    if len(body) > _MAX_METADATA_BYTES:
        raise ConfigError(f"{model_id}: endpoint metadata is oversized")
    reply_json = json.loads(body.decode("utf-8"))
    data = (
        cast(dict[str, Any], reply_json).get("data")
        if isinstance(reply_json, dict)
        else None
    )
    if not isinstance(data, dict) or not cast(dict[str, Any], data).get(
        "endpoints"
    ):
        raise ConfigError(f"{model_id}: no endpoint list")
    return cast(dict[str, Any], data)


def _tag(endpoint: dict[str, Any]) -> str:
    return str(endpoint.get("tag", ""))


def provider_tags(endpoints: Sequence[dict[str, Any]], route: str) -> list[str]:
    """Lists every endpoint tag the route's provider serves for the model."""
    provider = route.split("/", 1)[0]
    return sorted(
        {
            _tag(endpoint)
            for endpoint in endpoints
            if _tag(endpoint).split("/", 1)[0] == provider
        }
    )


def matched_endpoints(
    endpoints: Sequence[dict[str, Any]], spec: ConfigSpec
) -> list[dict[str, Any]]:
    """Returns the endpoints the spec's slug routes to, under the note's rule.

    A base slug is sent only when the provider serves one endpoint of the
    model, or when the spec is marked as spanning several; a full tag is
    sent only when the provider serves more than one.

    Raises:
        ConfigError: If nothing matches, or the slug breaks the rule.
    """
    tags = provider_tags(endpoints, spec.route)
    if not tags:
        raise ConfigError(f"{spec.name}: no endpoint matches {spec.route}")
    if "/" in spec.route:
        if len(tags) < 2:
            raise ConfigError(
                f"{spec.name}: the provider serves one endpoint; send the"
                " base slug"
            )
        wanted = {spec.route}
    else:
        if len(tags) > 1 and not spec.spans_endpoints:
            raise ConfigError(
                f"{spec.name}: {spec.route} matches {tags}; send a full tag"
            )
        wanted = set(tags)
    matched = [e for e in endpoints if _tag(e) in wanted]
    if not matched:
        raise ConfigError(f"{spec.name}: no endpoint matches {spec.route}")
    return matched


def _per_million(value: object) -> Decimal:
    """Converts an OpenRouter per-token price to USD per million tokens."""
    return Decimal(str(value)) * 1_000_000


def endpoint_price(endpoint: dict[str, Any]) -> tuple[Decimal, Decimal, str]:
    """Returns the listed input and output price and a note on any discount.

    Raises:
        ConfigError: If the endpoint bills something the bound ignores.
    """
    pricing = cast(dict[str, object], endpoint.get("pricing") or {})
    for key, value in pricing.items():
        if key not in _IGNORED_PRICING and Decimal(str(value)) != 0:
            raise ConfigError(f"{_tag(endpoint)}: unbounded price {key}")
    rate_in = _per_million(pricing["prompt"])
    rate_out = _per_million(pricing["completion"])
    discount = Decimal(str(pricing.get("discount", 0)))
    note = ""
    if discount > 0:
        full_in = (rate_in / (1 - discount)).quantize(Decimal("0.0001"))
        full_out = (rate_out / (1 - discount)).quantize(Decimal("0.0001"))
        note = (
            f"; {_tag(endpoint)} lists discount {discount.normalize():f},"
            " the listed price is recorded and bounds a request only while"
            f" the discount lasts (undiscounted {full_in.normalize():f}"
            f"/{full_out.normalize():f})"
        )
    return rate_in, rate_out, note


def _check_endpoints(spec: ConfigSpec, matched: list[dict[str, Any]]) -> str:
    """Refuses an endpoint that cannot carry the request; names the provider.

    Raises:
        ConfigError: If a matched endpoint lacks a sent parameter or the
            output ceiling, or the slug spans several providers.
    """
    required = SENT_PARAMETERS + (("reasoning",) if spec.reasoning else ())
    for endpoint in matched:
        supported = set(
            cast(list[str], endpoint.get("supported_parameters") or [])
        )
        missing = [name for name in required if name not in supported]
        if missing:
            raise ConfigError(f"{spec.name}: {_tag(endpoint)} lacks {missing}")
        ceiling = cast(int | None, endpoint.get("max_completion_tokens"))
        if (ceiling or 0) < MAX_OUTPUT_TOKENS:
            raise ConfigError(f"{spec.name}: output ceiling below 2048")
    names = {str(endpoint.get("provider_name")) for endpoint in matched}
    if len(names) != 1:
        raise ConfigError(f"{spec.name}: the slug spans several providers")
    return names.pop()


def _prices(
    spec: ConfigSpec,
    matched: list[dict[str, Any]],
    provider_name: str,
    fetched_at: str,
) -> dict[str, Any]:
    """Records the highest listed price of the matched endpoints and why."""
    prices = [endpoint_price(endpoint) for endpoint in matched]
    tags = sorted({_tag(endpoint) for endpoint in matched})
    quants = "/".join(sorted({str(e.get("quantization")) for e in matched}))
    span = "" if len(tags) == 1 else "; highest listed price of the matched"
    notes = "".join(sorted({price[2] for price in prices}))
    return {
        "usd_per_million_input": float(max(price[0] for price in prices)),
        "usd_per_million_output": float(max(price[1] for price in prices)),
        "source": (
            f"OpenRouter endpoints API for {spec.model_id}, slug {spec.route}"
            f" matches {', '.join(tags)} ({provider_name}, {quants}), fetched"
            f" {fetched_at}{span}{notes}"
        ),
    }


def build_config(
    spec: ConfigSpec, data: dict[str, Any], fetched_at: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Builds one explicit configuration and the endpoint facts behind it.

    Args:
        spec: The configuration to build.
        data: The model's endpoint metadata.
        fetched_at: The UTC fetch time recorded in the price source.

    Returns:
        The configuration mapping and a record of the matched endpoints.

    Raises:
        ConfigError: If the slug breaks the note's rule, or a matched
            endpoint cannot take a parameter the request sends.
    """
    endpoints = cast(list[dict[str, Any]], data["endpoints"])
    matched = matched_endpoints(endpoints, spec)
    provider_name = _check_endpoints(spec, matched)
    config = {
        "endpoint_url": ENDPOINT_URL,
        "settings": {
            "model_id": spec.model_id,
            "temperature": 0.0,
            "seed": 17,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "timeout_seconds": 120.0,
            "json_mode": True,
            "openrouter": {
                "reasoning": spec.reasoning,
                "provider_order": [spec.route],
                "allow_fallbacks": False,
                "require_parameters": True,
                "data_collection": None,
            },
        },
        "prices": _prices(spec, matched, provider_name, fetched_at),
    }
    facts = {
        "model_id": spec.model_id,
        "route": spec.route,
        "reasoning": spec.reasoning,
        "provider_name": provider_name,
        "provider_endpoint_tags": provider_tags(endpoints, spec.route),
        "fetched_at": fetched_at,
        "endpoints": [
            {key: endpoint.get(key) for key in _ENDPOINT_FACTS}
            for endpoint in matched
        ],
    }
    return config, facts


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_configs(
    built: dict[str, dict[str, Any]],
    facts: dict[str, dict[str, Any]],
    force: bool,
) -> None:
    """Writes each configuration and the endpoint facts behind them.

    An existing configuration is kept without ``force``, and keeps the
    endpoint facts it was built from.
    """
    config_dir = ROOT / CONFIG_DIR
    endpoints_file = ROOT / ENDPOINTS_FILE
    previous: dict[str, Any] = {}
    if endpoints_file.exists():
        previous = json.loads(endpoints_file.read_text(encoding="utf-8"))
    config_dir.mkdir(parents=True, exist_ok=True)
    for name, config in built.items():
        path = config_dir / f"{name}.json"
        if path.exists() and not force:
            facts[name] = previous.get("configs", {}).get(name, facts[name])
            print(f"kept {path.name} (exists; --force replaces it)")
            continue
        path.write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
        print(f"wrote {path.name}")
    for path in sorted(config_dir.glob("*.json")):
        if path.stem not in built:
            print(f"not in SPECS, left as it is: {path.name}")
    endpoints_file.write_text(
        json.dumps({"configs": facts}, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Fetches, builds, validates and writes every configuration."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--force", action="store_true")
    arguments = parser.parse_args(argv)
    model_run = load_model_run()
    fetched_at = _now()
    metadata: dict[str, dict[str, Any]] = {}
    built: dict[str, dict[str, Any]] = {}
    facts: dict[str, dict[str, Any]] = {}
    for spec in SPECS:
        if spec.model_id not in metadata:
            metadata[spec.model_id] = fetch_endpoints(spec.model_id)
        config, fact = build_config(spec, metadata[spec.model_id], fetched_at)
        model_run.CallConfigV1.model_validate(config)
        built[spec.name] = config
        facts[spec.name] = fact
    write_configs(built, facts, bool(arguments.force))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
