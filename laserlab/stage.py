import serial
import time

class ProScanStage:
    def __init__(self, port: str, wait_time: float = 1e-2):
        """The proscan III control instance.

        Args:
            port (str): The port name.
            wait_time (float, optional): The maximum time to wait for
                the stage to reach the target position in seconds.
                Defaults to 10 ms.
        """
        self.ser = serial.Serial(port, baudrate=9600, timeout=1)
        self.wait_time = wait_time
        self.steps_per_micron = float(self.info[4].split(" = ")[-1])
        self._velocity = self.velocity

    @property
    def info(self) -> list[str]:
        self.ser.write("STAGE\r".encode())
        lines = self.ser.readlines()[0]
        lines = lines.decode().split("\r")
        return lines
    
    @property
    def velocity(self) -> float:
        self.ser.write("SMS,i\r".encode())
        return float(self.ser.read_until(b"\r").decode().strip())

    def is_close(
            self,
            pos1: tuple[float, float],
            pos2: tuple[float, float],
            threshold: float = 10
        ) -> bool:
        """Check if two positions are close enough within a threshold."""
        dx = abs(pos1[0] - pos2[0])
        dy = abs(pos1[1] - pos2[1])
        if dx < threshold and dy < threshold:
            return True
        return False
    
    @property
    def is_stop(self) -> bool:
        pos1 = self.position
        time.sleep(1e-2)
        pos2 = self.position
        if self.is_close(pos1, pos2):
            return True
        return False
    
    def wait(self, max_time: float = 1):
        i = 0
        while not self.is_stop:
            time.sleep(1e-2)
            i += 1
            if i >= max_time / 1e-2:
                break

    @property
    def position(self) -> tuple[float, float]:
        """Return the current position of the stage as a tuple (x, y)."""
        self.ser.write(b"P\r")
        response = self.ser.read_until(b"\r").decode().strip()
        if response[0] == "E":
            return (-1, -1)
        if "\r" in response:
            response = response.split("\r")[-1]
        x, y, _ = response.split(',')
        return float(x), float(y)

    def move_to(self, x: int, y: int):
        """Move the stage to the specified (x, y) position."""
        command = f"G {x},{y}\r".encode()
        self.ser.write(command)
        response = self.ser.read_until(b"\r").decode().strip()
        if response != "R":
            raise RuntimeWarning("Stage is not correctly moving!")

    def move_by(self, dx: int, dy: int):
        command = f"GR {dx},{dy}\r".encode()
        self.ser.write(command)
        response = self.ser.read_until(b"\r").decode().strip()
        if response != "R":
            raise RuntimeWarning("Stage is not correctly moving!")

    def scan(
            self,
            positions: list[tuple[int, int]],
            intervals: list[float] | float = 0):
        for i, pos in enumerate(positions):
            self.move_to(*pos)
            if isinstance(intervals, list) and i < len(intervals):
                time.sleep(intervals[i])
            elif isinstance(intervals, (int, float)):
                time.sleep(intervals)

    def close(self):
        self.ser.close()
