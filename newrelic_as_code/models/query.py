"""NRQL query model."""

from typing import Any

from .base import NrModel


class NrqlQuery(NrModel):
    """A single NRQL query inside a widget's ``nrqlQueries``.

    NerdGraph accepts either ``accountId`` (a single account) or ``accountIds``
    (an array, for multi-account queries). Leave both unset to let
    ``NewRelicUpdater`` inject its own account id at reconcile time.
    """

    query: str
    account_id: int | None = None
    account_ids: list[int] | None = None

    def as_nr_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"query": self.query}
        if self.account_ids is not None:
            result["accountIds"] = self.account_ids
        if self.account_id is not None:
            result["accountId"] = self.account_id
        return result
