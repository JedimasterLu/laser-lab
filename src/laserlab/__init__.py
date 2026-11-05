"""Hardware control utilities for the laser lab.

Submodules are imported lazily, so ``import laserlab`` works without the
optional camera, SLM or reinforcement-learning dependencies installed.
"""

from importlib import import_module

_EXPORTS = {
    "SC30Shutter": "shutter",
    "Chopper": "chopper",
    "MC2000BChopper": "chopper",
    "ProScanStage": "stage",
    "print_ports": "utils",
    "LaserControl": "laser",
    "EXULUS": "slm",
    "NikonDSFi3Camera": "camera",
    "LaserTrapEnv": "gym",
    "NanoparticleStageEnv": "gym",
    "TrackpyDetector": "gym",
    "SimLaserEnv": "sim",
    "NikonTi2": "ti2",
    "MockStage": "mock",
    "MockShutter": "mock",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    """Import the submodule that defines ``name`` on first access.

    Args:
        name: Public attribute requested from the package.

    Returns:
        The requested class or function.

    Raises:
        AttributeError: If ``name`` is not a public attribute.
    """
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(f".{_EXPORTS[name]}", __name__), name)
