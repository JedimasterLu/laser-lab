"""Default stage profile. Nothing is persisted; the profile travels inside project files."""

from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "model": "H101/2",
    "x_range_um": [0, 108000],
    "y_range_um": [0, 71000],
    "units_per_um": 100.0,
}
"""Stage profile defaults taken from the ProScan III manual's ``STAGE`` example."""


def load() -> dict[str, Any]:
    """Return a copy of the default stage profile."""
    return {**DEFAULTS}
