"""Project files (``.laserscan.json``): shapes, parameters and the stage profile."""

from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from pathlib import Path
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

    Unknown scan parameters are ignored so that files from a later minor revision still open.

    Args:
        text: JSON text produced by ``dumps``.

    Returns:
        Shapes, scan parameters and the stage profile stored in the file.

    Raises:
        ValueError: If the file is malformed, has a newer version, or uses another coordinate system.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"This is not a LaserScan project file ({exc.msg}).") from exc
    if not isinstance(data, dict) or "shapes" not in data or "params" not in data:
        raise ValueError("This is not a LaserScan project file (no shapes or params).")
    if data.get("version", 0) > VERSION:
        raise ValueError(f"The file was saved by a newer LaserScan (format {data['version']}, this one reads up to {VERSION}).")
    if data.get("coordinates") == "stage-absolute":
        raise ValueError("The file uses absolute stage coordinates (an old format); redraw it relative to the start position.")
    if data.get("units") != "um" or data.get("coordinates") != "relative":
        raise ValueError(f"Unsupported units {data.get('units')!r} or coordinates {data.get('coordinates')!r}.")
    known = {f.name for f in fields(Params)}
    params = Params(**{k: v for k, v in data["params"].items() if k in known})
    if params.pattern not in PATTERNS:  # e.g. the removed "contour" pattern
        params = replace(params, pattern=Params().pattern)
    return data["shapes"], params, data.get("stage_profile", {})


def save(path: str | Path, shapes: list[dict], params: Params, profile: dict[str, Any]) -> None:
    """Write a project file; the old file stays intact if writing fails part-way.

    Args:
        path: Destination (UTF-8, ``\\n`` line ends on every platform).
        shapes: Shape dictionaries.
        params: Scan parameters.
        profile: Stage profile.
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(shapes, params, profile) + "\n")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load(path: str | Path) -> tuple[list[dict], Params, dict[str, Any]]:
    """Read a project file; see :func:`loads`."""
    return loads(Path(path).read_text(encoding="utf-8-sig"))
