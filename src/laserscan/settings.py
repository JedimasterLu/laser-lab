"""Default stage profile. Nothing is persisted; the profile travels inside project files."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "model": "H117(1MM)",
    "x_range_um": [0, 114000],
    "y_range_um": [0, 75000],
    "units_per_um": 100.0,
}
"""Stage profile defaults for the lab's H117 (1 mm pitch) stage, from its real ``STAGE`` reply (SIZE_X 114 mm, SIZE_Y 75 mm)."""


def load() -> dict[str, Any]:
    """Return a copy of the default stage profile."""
    return {**DEFAULTS}
