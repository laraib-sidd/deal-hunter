"""Alert pipeline — score delta, decide, match watches, dispatch."""

from deal_hunter.alerts.match import match_watches
from deal_hunter.alerts.pipeline import decide_alerts, dispatch, score_delta

__all__ = ["decide_alerts", "dispatch", "match_watches", "score_delta"]
