from typing import Literal
import serial

class SC30Shutter:
    def __init__(self, port: str):
        """The SC30 shutter control instance.

        Args:
            port (str): The port name.
        """
        self.ser = serial.Serial(port, baudrate=115200, timeout=1)
        self.set_mode('manual')
        self.unlock()
        self.close()

    def unlock(self):
        self.ser.write(b"unlocked=1\r")
        self.ser.read_until(b">").decode().strip()

    def open(self, channel: int = 1):
        """Open the shutter."""
        self.ser.write(f"enable{channel}=1\r".encode())
        self.ser.read_until(b">").decode().strip()
    
    def close(self, channel: int = 1):
        """Close the shutter."""
        self.ser.write(f"enable{channel}=0\r".encode())
        self.ser.read_until(b">").decode().strip()
    
    def is_open(self, channel: int = 1) -> bool:
        """Check if the shutter is open."""
        command = ''
        if self.mode() == 'manual':
            command = f"enable{channel}?\r"
        else:
            command = f"triggerstate{channel}?\r"
        self.ser.write(command.encode())
        response = self.ser.read_until(b">").decode().strip()
        if "0" not in response:
            return True
        return False
    
    def is_closed(self, channel: int = 1) -> bool:
        """Check if the shutter is closed."""
        command = ''
        if self.mode() == 'manual':
            command = f"enable{channel}?\r"
        else:
            command = f"triggerstate{channel}?\r"
        self.ser.write(command.encode())
        response = self.ser.read_until(b">").decode().strip()
        if "0" in response:
            return True
        return False
    
    def set_mode(self, mode: Literal['manual', 'internal']):
        if mode not in ['manual', 'internal']:
            raise ValueError("Only 'manual' and 'internal' are supported")
        if mode == 'manual':
            self.ser.write("mode=0\r".encode())
            self.ser.read_until(b">").decode().strip()
        elif mode == 'internal':
            self.ser.write("mode=2\r".encode())
            self.ser.read_until(b">").decode().strip()
        self.unlock()

    def mode(self) -> Literal['manual', 'internal']:
        self.ser.write("mode?\r".encode())
        response = self.ser.read_until(b">").decode().strip()
        if "0" in response:
            return 'manual'
        elif "2" in response:
            return 'internal'
        raise ValueError("Unknown mode")

    def set_freq(self, freq: float, channel: int = 1):
        if freq > 50 or freq < 0.1:
            raise ValueError("Frequency must be between [0.1, 50.0]")
        self.ser.write(f"intfreq{channel}={freq}\r".encode())
        self.ser.read_until(b">").decode().strip()
