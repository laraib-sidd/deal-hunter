from __future__ import annotations

import pytest

from deal_hunter.analysis.normalizer import HardwareNormalizer


@pytest.fixture
def normalizer() -> HardwareNormalizer:
    return HardwareNormalizer()
