"""DFilterForge typed display-filter compiler and evaluation core."""

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.compiler import compile_intent
from dfilterforge.evaluation import evaluate_probe
from dfilterforge.intent_ir import IntentIrV1

__all__ = [
    "IntentIrV1",
    "canonical_json",
    "compile_intent",
    "content_sha256",
    "evaluate_probe",
]

__version__ = "0.1.0"
