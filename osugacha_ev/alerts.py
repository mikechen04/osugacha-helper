"""fuel quicksell detection.

a quicksell is a fresh listing sitting at least pct percent under the next
lowest lbin. the lowest one or two listings count, so a pair of cheap
listings is caught as long as both are under the rest of the market.
"""

from __future__ import annotations

from dataclasses import dataclass

from osugacha_ev.api import Listing
from osugacha_ev.config import ALERT_MAX_AGE, ALERT_MAX_CLUSTER


@dataclass(frozen=True)
class Alert:
    listing: Listing
    next_lbin: float
    below_pct: float  # how far under the next lbin, 18.9 = 18.9% lower
    age: float  # seconds since it was listed


def detect(
    listings: list[Listing],
    pct: float,
    now: float,
    *,
    max_age: float = ALERT_MAX_AGE,
    max_cluster: int = ALERT_MAX_CLUSTER,
) -> list[Alert]:
    """fresh listings in the bottom cluster that sit pct% under the next lbin."""
    ordered = sorted(listings, key=lambda l: l.unit)
    limit = 1 - pct / 100
    for k in range(min(max_cluster, len(ordered) - 1)):
        # the cluster is ordered[: k + 1], the next lbin is ordered[k + 1]
        next_unit = ordered[k + 1].unit
        if ordered[k].unit <= next_unit * limit:
            return [
                Alert(l, next_unit, (1 - l.unit / next_unit) * 100, now - l.created_at)
                for l in ordered[: k + 1]
                if l.created_at and now - l.created_at <= max_age
            ]
    return []
