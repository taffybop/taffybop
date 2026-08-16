from __future__ import annotations

import pytest

from tests.benchmarks.font_audit_metrics import _nearest_rank


def test_font_audit_metric_percentiles_use_nearest_rank() -> None:
    values = [5.0, 1.0, 4.0, 2.0, 3.0]

    assert _nearest_rank(values, 0.50) == 3.0
    assert _nearest_rank(values, 0.95) == 5.0
    with pytest.raises(ValueError, match="at least one"):
        _nearest_rank([], 0.95)
