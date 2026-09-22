from __future__ import annotations

import re
from typing import Literal

import serial


Ring = Literal["inner", "outer"]


class Chopper:
	"""Controller for a Thorlabs MC2000B with an MC1F10HP blade."""

	MODEL = "MC1F10HP"
	BLADE_INDEX = 6
	INNER_SLOTS = 10
	OUTER_SLOTS = 100
	MIN_FREQUENCY_HZ = 200.0
	MAX_FREQUENCY_HZ = 10000.0

	_REFERENCE_MODES: dict[Ring, int] = {"outer": 0, "inner": 1}
	_OUTPUT_MODES: dict[Ring, int] = {"outer": 1, "inner": 2}

	def __init__(
		self,
		port: str,
		baudrate: int = 115200,
		timeout: float = 1.0,
	) -> None:
		self.ser = serial.Serial(port, baudrate=baudrate, timeout=timeout)
		self._ring: Ring = "inner"
		self._configure_blade()

	def _send_command(self, command: str) -> str:
		self.ser.write(f"{command}\r".encode("ascii"))
		response = self.ser.read_until(b">").decode("ascii", errors="replace").strip()
		if not response:
			raise TimeoutError(f"No response received for command {command!r}")
		if response.startswith("CMD_ARG_"):
			raise ValueError(
				f"Chopper rejected command {command!r}: {response}"
			)
		return response

	def _query_number(self, command: str) -> float:
		response = self._send_command(command)
		match = re.search(r"[-+]?\d+(?:\.\d+)?", response)
		if match is None:
			raise ValueError(f"Unexpected response from chopper: {response!r}")
		return float(match.group())

	def _configure_blade(self) -> None:
		self._send_command(f"blade={self.BLADE_INDEX}")
		# The manual's internal-reference setup uses INT-OUTER for MC1F10HP.
		self._set_ring("outer")

	def _set_ring(self, ring: Ring) -> None:
		self._send_command(f"ref={self._REFERENCE_MODES[ring]}")
		self._send_command(f"output={self._OUTPUT_MODES[ring]}")
		self._ring = ring

	@property
	def ring(self) -> Ring:
		"""Return the currently selected blade ring."""
		return self._ring

	def switch_ring(self, ring: Ring) -> None:
		"""Switch between the inner and outer MC1F10HP blade rings."""
		if ring not in self._REFERENCE_MODES:
			raise ValueError("ring must be 'inner' or 'outer'")
		self._set_ring(ring)

	def start(self) -> None:
		"""Start the chopper motor."""
		self._send_command("enable=1")

	def stop(self) -> None:
		"""Stop the chopper motor."""
		self._send_command("enable=0")

	def set_frequency(self, frequency_hz: float) -> None:
		"""Set the selected ring's frequency in Hz."""
		if not self.MIN_FREQUENCY_HZ <= frequency_hz <= self.MAX_FREQUENCY_HZ:
			raise ValueError(
				f"Frequency must be between {self.MIN_FREQUENCY_HZ:g} and "
				f"{self.MAX_FREQUENCY_HZ:g} Hz"
			)
		self._send_command(f"freq={round(frequency_hz):d}")

	def get_frequency(self) -> float:
		"""Read the actual pulse frequency of the selected blade ring."""
		return self._query_number("refoutfreq?")

	def get_rotation_frequency(self) -> float:
		"""Return the mechanical blade rotation frequency in revolutions/sec."""
		slots = self.INNER_SLOTS if self._ring == "inner" else self.OUTER_SLOTS
		return self.get_frequency() / slots

	def get_reference_frequency(self) -> float:
		"""Read the controller's internal reference frequency."""
		return self._query_number("freq?")

	def close(self) -> None:
		"""Stop the motor and close the serial connection."""
		if self.ser.is_open:
			try:
				self.stop()
			finally:
				self.ser.close()

	def __enter__(self) -> Chopper:
		return self

	def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
		self.close()

	def __del__(self) -> None:
		try:
			self.close()
		except Exception:
			pass


MC2000BChopper = Chopper
