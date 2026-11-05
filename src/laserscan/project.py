"""Project files (``.laserscan.json``): shapes, parameters and the stage profile."""

from __future__ import annotations

import json
from dataclasses import asdict, replace
from typing import Any

from laserscan.planning import PATTERNS, Params, clean_shape

VERSION = 1


def dumps(shapes: list[dict], params: Params, profile: dict[str, Any]) -> str:
    """Serialize a project.

    Args:
        shapes: Shape dictionaries in microns relative to the starting stage position.
        params: Scan parameters.
        profile: Stage profile the shapes were drawn for.

    Returns:
        The project as JSON text.
    """
    return json.dumps(
        {
            "version": VERSION,
            "units": "um",
            "coordinates": "relative",
            "stage_profile": profile,
            "params": asdict(params),
            "shapes": [clean_shape(s) for s in shapes],
        },
        indent=2,
    )


def loads(text: str) -> tuple[list[dict], Params, dict[str, Any]]:
    """Parse a project.

    Args:
        text: JSON text produced by ``dumps``.

    Returns:
        Shapes, scan parameters and the stage profile stored in the file.

    Raises:
        ValueError: If the file is malformed or has a newer version.
    """
    data = json.loads(text)
    if data.get("version", 0) > VERSION or data.get("units") != "um" or data.get("coordinates") != "relative":
        raise ValueError("Unsupported project file version, units or coordinates.")
    params = Params(**data["params"])
    if params.pattern not in PATTERNS:  # e.g. the removed "contour" pattern
        params = replace(params, pattern=Params().pattern)
    return data["shapes"], params, data.get("stage_profile", {})
