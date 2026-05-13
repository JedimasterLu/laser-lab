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

    def if_close(
            self,
            pos1: tuple[float, float],
            pos2: tuple[float, float],
            threshold: float = 1e-3
        ) -> bool:
        """Check if two positions are close enough within a threshold."""
        dx = pos1[0] - pos2[0]
        dy = pos1[1] - pos2[1]
        if abs(dx) / max(abs(pos1[0]), abs(pos2[0])) < threshold and \
           abs(dy) / max(abs(pos1[1]), abs(pos2[1])) < threshold:
            return True
        return False

    @property
    def position(self) -> tuple[float, float]:
        """Return the current position of the stage as a tuple (x, y)."""
        self.ser.write(b"P<CR>")
        response = self.ser.readline().decode().strip()
        x, y, _ = response.split(',')
        return float(x), float(y)

    def move_to(self, x: int, y: int) -> bool:
        """Move the stage to the specified (x, y) position."""
        command = f"G {x},{y}<CR>".encode()
        self.ser.write(command)
        t = 0
        while not self.if_close(self.position, (x, y)):
            time.sleep(1e-3)
            t += 1e-3
            if t > self.wait_time:
                return False
        return True
    
    def move_by(self, dx: int, dy: int) -> bool:
        command = f"GR {dx},{dy}<CR>".encode()
        self.ser.write(command)
        t = 0
        while not self.if_close(
                self.position,
                (self.position[0] + dx, self.position[1] + dy)):
            time.sleep(1e-3)
            t += 1e-3
            if t > self.wait_time:
                return False
        return True
    
    def scan(
            self,
            positions: list[tuple[int, int]],
            intervals: list[float] | float = 0) -> bool:
        for i, pos in enumerate(positions):
            if not self.move_to(*pos):
                return False
            if isinstance(intervals, list) and i < len(intervals):
                time.sleep(intervals[i])
            elif isinstance(intervals, (int, float)):
                time.sleep(intervals)
        return True

    def close(self):
        self.ser.close()
