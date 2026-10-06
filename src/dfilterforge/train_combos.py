"""Grammar-sampled training compositions and their plain-English requests.

Candidate ``index`` of a sampler seed depends on nothing but the two numbers,
so a build over the first k candidates is a prefix of any longer build. A
composition joins one to three atoms of :mod:`dfilterforge.train_atoms`,
no two on the same field, at depth at most 2; a leaf may be negated, and a
nested group holds plain predicates. A seeded share of the candidates
becomes a needs_clarification target: one atom's wording is replaced by the
wording that leaves its slot open, as the dev and test non-ready gold does
with a status and its missing slots. Nothing here reads evaluator gold.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
import random
import re
from typing import TypeAlias

from dfilterforge.canonical import canonical_json
from dfilterforge.canonical import content_sha256
from dfilterforge.intent_ir import All
from dfilterforge.intent_ir import AnyOf
from dfilterforge.intent_ir import Expression
from dfilterforge.intent_ir import GenerationResultV1
from dfilterforge.intent_ir import GenerationStatus
from dfilterforge.intent_ir import IntentIrV1
from dfilterforge.intent_ir import Not
from dfilterforge.intent_ir import Operator
from dfilterforge.intent_ir import Predicate
from dfilterforge.intent_ir import walk_predicates
from dfilterforge.train_atoms import APPS
from dfilterforge.train_atoms import Atom
from dfilterforge.train_atoms import ATOMS
from dfilterforge.train_atoms import HOSTS
from dfilterforge.train_atoms import QUESTIONS

# A shape is "L" (a predicate, maybe negated), "P" (a plain predicate) or
# a node: ("all" | "any", child, ...) or ("not", group). Each predicate
# count maps to its shapes with their sampling weights.
Shape: TypeAlias = str | tuple["Shape", ...]
SHAPES: dict[int, tuple[tuple[Shape, int], ...]] = {
    1: (("L", 1),),
    2: (
        (("all", "L", "L"), 3),
        (("any", "L", "L"), 2),
        (("not", ("any", "P", "P")), 1),
    ),
    3: (
        (("all", "L", "L", "L"), 3),
        (("any", "L", "L", "L"), 2),
        (("all", "L", ("any", "P", "P")), 2),
        (("any", "L", ("all", "P", "P")), 1),
        (("not", ("any", "P", "P", "P")), 1),
    ),
}
PREDICATE_WEIGHTS = (1, 5, 5)
# The word-run length of the text overlap check against dev and test.
NGRAM = 8
NEGATION_SHARE = 0.1
NON_READY_SHARE = 0.18
FRAMES = (
    "Show packets that {}.",
    "Find the packets that {}.",
    "I need all packets that {}.",
    "Filter for packets that {}.",
    "Keep only packets that {}.",
    "Give me the packets that {}.",
    "Which packets {}?",
    "List the packets that {}.",
)


@dataclass(frozen=True)
class TrainCombo:
    """One sampled composition, its request and the answer it teaches.

    Attributes:
        index: The candidate number under the sampler seed.
        expression: The sampled composition, in request order.
        request: The plain-English request.
        target: The envelope a model should return for ``request``.
    """

    index: int
    expression: Expression
    request: str
    target: GenerationResultV1


def canonical_expression(expression: Expression) -> Expression:
    """Returns the expression with All and AnyOf flattened and sorted.

    Nested groups of the same kind merge into their parent, children are
    ordered by their canonical JSON, and ``in`` value lists are sorted, so
    two spellings of one composition share a form.
    """
    if isinstance(expression, Predicate):
        if isinstance(expression.value, tuple):
            ordered = tuple(sorted(expression.value, key=canonical_json))
            return expression.model_copy(update={"value": ordered})
        return expression
    if isinstance(expression, Not):
        return Not(child=canonical_expression(expression.child))
    children: list[Expression] = []
    for child in map(canonical_expression, expression.children):
        if type(child) is type(expression):
            assert isinstance(child, (All, AnyOf))
            children.extend(child.children)
        else:
            children.append(child)
    ordered_children = tuple(sorted(children, key=canonical_json))
    return type(expression)(children=ordered_children)


def canonical_key(expression: Expression) -> str:
    """Returns the SHA-256 of the canonical form's typed intent."""
    return content_sha256(
        IntentIrV1(expression=canonical_expression(expression))
    )


def depth(expression: Expression) -> int:
    """Returns the number of logical nodes on the longest root-leaf path."""
    if isinstance(expression, Predicate):
        return 0
    if isinstance(expression, Not):
        return 1 + depth(expression.child)
    return 1 + max(depth(child) for child in expression.children)


def _negatable(atom: Atom) -> bool:
    """Whether a request can negate the atom without a double negative."""
    return (
        atom.predicate.operator != Operator.NE
        and atom.predicate.value is not False
    )


def _build(
    shape: Shape, rng: random.Random, used: list[Atom], negated: bool = False
) -> Expression:
    """Builds ``shape`` from atoms on unused fields, appending each to ``used``.

    Leaves under a ``not`` group, and leaves negated themselves, are drawn
    only from atoms a request can negate plainly.
    """
    if isinstance(shape, str):
        fields = {atom.predicate.field for atom in used}
        atom = rng.choice(
            [
                atom
                for atom in ATOMS
                if atom.predicate.field not in fields
                and (_negatable(atom) or not negated)
            ]
        )
        used.append(atom)
        if shape == "L" and _negatable(atom) and rng.random() < NEGATION_SHARE:
            return Not(child=atom.predicate)
        return atom.predicate
    kind, *parts = shape
    children = tuple(
        _build(part, rng, used, negated or kind == "not") for part in parts
    )
    if kind == "not":
        return Not(child=children[0])
    return (All if kind == "all" else AnyOf)(children=children)


def _join(parts: list[str], word: str) -> str:
    return f"{', '.join(parts[:-1])} {word} {parts[-1]}"


def _negate(wording: str) -> str:
    if wording.startswith("are "):
        return f"are not {wording.removeprefix('are ')}"
    return f"do not {wording}"


def render(expression: Expression, wording: dict[Predicate, str]) -> str:
    """Words an expression as a verb phrase completing "packets that".

    Args:
        expression: A composition the sampler can build.
        wording: The phrase chosen for each of its predicates.

    Returns:
        The phrase; a nested group reads "either ... or" or "both ... and".
    """
    if isinstance(expression, Predicate):
        return wording[expression]
    if isinstance(expression, Not):
        if isinstance(expression.child, Predicate):
            return _negate(wording[expression.child])
        assert isinstance(expression.child, AnyOf)
        parts = [render(child, wording) for child in expression.child.children]
        return "neither " + _join(parts, "nor")
    parts = [
        ("both " if isinstance(child, All) else "") + render(child, wording)
        for child in expression.children
    ]
    if isinstance(expression, AnyOf):
        return "either " + _join(parts, "or")
    return _join(parts, "and")


def _vague(atom: Atom, rng: random.Random) -> str:
    return atom.vague.format(host=rng.choice(HOSTS), app=rng.choice(APPS))


def sample_combo(seed: int, index: int) -> TrainCombo:
    """Samples candidate ``index`` of sampler ``seed``.

    Args:
        seed: The sampler seed.
        index: The candidate number, from 0.

    Returns:
        The composition, its request and its ready or needs_clarification
        target.
    """
    rng = random.Random(f"train-combos/{seed}/{index}")
    count = rng.choices((1, 2, 3), weights=PREDICATE_WEIGHTS)[0]
    shapes = [shape for shape, _ in SHAPES[count]]
    weights = [weight for _, weight in SHAPES[count]]
    atoms: list[Atom] = []
    expression = _build(rng.choices(shapes, weights)[0], rng, atoms)
    wording = {atom.predicate: rng.choice(atom.wordings) for atom in atoms}
    frame = rng.choice(FRAMES)
    vague = [atom for atom in atoms if atom.slot is not None]
    if vague and rng.random() < NON_READY_SHARE:
        dropped = rng.choice(vague)
        assert dropped.slot is not None
        wording[dropped.predicate] = _vague(dropped, rng)
        target = GenerationResultV1(
            status=GenerationStatus.NEEDS_CLARIFICATION,
            clarifying_question=QUESTIONS[dropped.slot],
            missing_slots=(dropped.slot,),
        )
    else:
        target = GenerationResultV1(
            status=GenerationStatus.READY,
            intent_ir=IntentIrV1(expression=expression),
        )
    request = frame.format(render(expression, wording))
    return TrainCombo(index, expression, request, target)


def ngrams(text: str, size: int = NGRAM) -> set[tuple[str, ...]]:
    """Returns the runs of ``size`` lowercase words and numbers in text."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {
        tuple(words[index : index + size])
        for index in range(len(words) - size + 1)
    }


def summarize(combos: Sequence[TrainCombo]) -> dict[str, object]:
    """Counts combos by status, open slot, depth, predicates and field."""
    tallies: dict[str, Counter[str]] = {
        key: Counter()
        for key in ("status", "slot", "depth", "predicates", "fields")
    }
    for combo in combos:
        predicates = walk_predicates(combo.expression)
        tallies["status"][combo.target.status.value] += 1
        tallies["slot"].update(s.value for s in combo.target.missing_slots)
        tallies["depth"][str(depth(combo.expression))] += 1
        tallies["predicates"][str(len(predicates))] += 1
        tallies["fields"].update({p.field for _, p in predicates})
    summary: dict[str, object] = {
        key: dict(sorted(tally.items())) for key, tally in tallies.items()
    }
    summary["total"] = len(combos)
    return summary
