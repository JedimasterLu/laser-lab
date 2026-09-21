from __future__ import annotations

import argparse
import time

from laserlab.chopper import Chopper


def scan_frequency(
	port: str,
	duration_s: float = 60.0,
	update_interval_s: float = 0.1,
) -> None:
	"""Sweep the selected MC1F10HP ring from its minimum to maximum frequency."""
	if duration_s <= 0:
		raise ValueError("duration_s must be greater than 0")
	if update_interval_s <= 0:
		raise ValueError("update_interval_s must be greater than 0")

	min_frequency = Chopper.MIN_FREQUENCY_HZ
	max_frequency = Chopper.MAX_FREQUENCY_HZ

	with Chopper(port) as chopper:
		chopper.start()
		start_time = time.monotonic()
		deadline = start_time + duration_s

		try:
			while True:
				now = time.monotonic()
				elapsed = now - start_time
				if now >= deadline:
					break

				progress = elapsed / duration_s
				frequency = min_frequency + (max_frequency - min_frequency) * progress
				chopper.set_frequency(frequency)
				time.sleep(min(update_interval_s, deadline - now))

			chopper.set_frequency(max_frequency)
		finally:
			chopper.stop()


def main() -> None:
	parser = argparse.ArgumentParser(description="Sweep an MC1F10HP chopper frequency.")
	parser.add_argument("port", help="Serial port, for example /dev/tty.usbserial-XXXX")
	parser.add_argument(
		"--duration",
		type=float,
		default=60.0,
		help="Scan duration in seconds (default: 60)",
	)
	parser.add_argument(
		"--interval",
		type=float,
		default=0.1,
		help="Frequency update interval in seconds (default: 0.1)",
	)
	args = parser.parse_args()
	scan_frequency(args.port, args.duration, args.interval)


if __name__ == "__main__":
	main()
