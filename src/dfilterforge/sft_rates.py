"""Two rates of the self-served rows: the coverage split and the seeds' mean.

The coverage split is the SFT headline's estimator (``docs/protocol.md``,
Training rules, amended 2026-10-18): per case, the share of its items in a
field-coverage stratum and strong exact over the share of its items in the
stratum, each summed over a resample's drawn cases, on the shared
resamples. The seeds' mean averages each case over the seeds, then over
the cases, as the headline averages the seeds. ``scripts/sft_analysis.py``
checks both against the headline wherever the headline holds them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dfilterforge.errors import DFilterForgeError
from dfilterforge.score_summary import case_means
from dfilterforge.score_summary import draw_indices
from dfilterforge.score_summary import OutcomeV1
from dfilterforge.score_summary import ratio_rate
from dfilterforge.sft_tables import covered
from dfilterforge.sft_tables import Document
from dfilterforge.sft_tables import Items
from dfilterforge.sft_tables import Keep
from dfilterforge.sft_tables import STRATA

_EXACT = OutcomeV1.STRONG_EXACT
_DIGITS = 6


def _shares(items: Items, keep: Keep, exact: bool) -> dict[str, float]:
    """Per case, the share of its items that ``keep`` takes.

    With ``exact``, only the strong-exact ones count.
    """
    return case_means(
        [
            (i.case_id, float(keep(i) and (i.outcome is _EXACT or not exact)))
            for i in items.values()
        ]
    )


def coverage(rows: Mapping[str, Items]) -> list[Document]:
    """Strong exact inside each coverage stratum, per row.

    Retrieval depends only on the prompt, so every row puts each item in the
    first row's stratum, and the strata's cases are the first row's.

    Args:
        rows: Each row's ready items by item id, by run id, the first row
            first.

    Returns:
        Per row, in order, each stratum's rate with its interval.

    Raises:
        DFilterForgeError: A row answers other items than the first row or
            puts an item in another stratum.
    """
    base = next(iter(rows.values()))
    case_ids = tuple(sorted({item.case_id for item in base.values()}))
    vectors = draw_indices(len(case_ids))
    present = {
        name: {
            key: share
            for key, share in _shares(base, keep, exact=False).items()
            if share
        }
        for name, keep in STRATA.items()
    }
    table: list[Document] = []
    for run, items in rows.items():
        if items.keys() != base.keys() or any(
            covered(item) != covered(base[key]) for key, item in items.items()
        ):
            raise DFilterForgeError("rows_differ", f"{run} differs")
        strata: Document = {}
        for name, keep in STRATA.items():
            exact = _shares(items, keep, exact=True)
            numerators = {key: exact[key] for key in present[name]}
            strata[name] = ratio_rate(
                numerators, present[name], vectors, case_ids
            ).model_dump()
        table.append({"run": run, "strata": strata})
    return table


def seed_mean(seeds: Sequence[Items]) -> float:
    """The seeds' strong exact on one condition: per case, then over cases."""
    shares = [
        case_means(
            [(i.case_id, float(i.outcome is _EXACT)) for i in items.values()]
        )
        for items in seeds
    ]
    cases = [
        sum(share[key] for share in shares) / len(shares) for key in shares[0]
    ]
    return round(sum(cases) / len(cases), _DIGITS)
