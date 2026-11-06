"""Process-wide state shared by the window and the shutdown handlers."""

from __future__ import annotations

from laserscan.devices import Devices
from laserscan.executor import Executor
from laserscan.planning import Params, Segment


class Session:
    """The single user session of the local server.

    Attributes:
        devices: Connected instruments.
        executor: Plan runner.
        plan: Current scan segments.
        params: Parameters the plan was built with.
        problems: Reasons the plan must not be run; empty if it may run.
    """

    def __init__(self) -> None:
        self.devices = Devices()
        self.executor = Executor(self.devices)
        self.plan: list[Segment] = []
        self.params = Params()
        self.problems: list[str] = []

    def shutdown(self, reason: str) -> None:
        """Abort any run and close all devices.

        Args:
            reason: Why the app is shutting down.
        """
        self.executor.abort(reason)
        self.devices.close()


SESSION = Session()
