import serial
import time

class SC30Shutter:
    def __init__(self, port: str, wait_time: float = 1e-2):
        """The SC30 shutter control instance.

        Args:
            port (str): The port name.
            wait_time (float, optional): The maximum time to wait for
                the shutter to reach the target state in seconds.
                Defaults to 10 ms.
        """
        self.ser = serial.Serial(port, baudrate=115200, timeout=1)
        self.wait_time = wait_time

        self.ser.write(b"unlocked=1\r\n")
        self.ser.write(b"mode=0\r\n")

    def open(self, channel: int = 1) -> bool:
        """Open the shutter."""
        if not self.is_open(channel):
            self.ser.write(f"enable{channel}=1\r\n".encode())
            t = 0
            while t < self.wait_time:
                self.ser.write(f"enable{channel}?\r\n".encode())
                response = self.ser.readline().decode().strip()
                if response == "1":
                    return True
                time.sleep(1e-3)
                t += 1e-3
        else:
            return True
        return False
    
    def close(self, channel: int = 1) -> bool:
        """Close the shutter."""
        if self.is_open(channel):
            self.ser.write(f"enable{channel}=0\r\n".encode())
            t = 0
            while t < self.wait_time:
                self.ser.write(f"enable{channel}?\r\n".encode())
                response = self.ser.readline().decode().strip()
                if response == "0":
                    return True
                time.sleep(1e-3)
                t += 1e-3
        else:
            return True
        return False
    
    def is_open(self, channel: int = 1) -> bool:
        """Check if the shutter is open."""
        self.ser.write(f"enable{channel}?\r\n".encode())
        response = self.ser.readline().decode().strip()
        if response == "1":
            return True
        return False
    
    def is_closed(self, channel: int = 1) -> bool:
        """Check if the shutter is closed."""
        self.ser.write(f"enable{channel}?\r\n".encode())
        response = self.ser.readline().decode().strip()
        if response == "0":
            return True
        return False
    
    def cycle(self, times: int, interval: float, channel: int = 1):
        """Cycle the shutter.

        Args:
            times (int): How many times to cycle the shutter.
            interval (float): In ms, the time interval between open and close.
            channel (int, optional): Defaults to 1.
        """
        self.close(channel)
        for _ in range(times):
            time.sleep(interval / 1e3)
            self.open(channel)
            time.sleep(interval / 1e3)
            self.close(channel)
