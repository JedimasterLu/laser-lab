import threading
import time
import warnings

import serial
from typing import Literal

class SC30Shutter:
    def __init__(self, port: str):
        """The SC30 shutter control instance."""
        # 1. Open the port
        self._lock = threading.RLock()
        self.ser = serial.Serial(port, baudrate=115200, timeout=1)
        
        # 2. WAIT for the controller to boot up / stabilize after serial connection
        time.sleep(2.0) 
        
        # Clear any garbage data left in the serial buffer from a previous run
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

        # 3. Unlock FIRST, then set mode, then close to establish a safe baseline
        self.unlock()
        self.set_mode('manual')
        self.close()

    def _send_cmd(self, cmd: str) -> str:
        """Helper to safely send a command, read the response, and warn on timeouts."""
        with self._lock:
            self.ser.write(cmd.encode())
            response = self.ser.read_until(b">").decode(errors="replace").strip()

        if not response:
            warnings.warn(f"Shutter timeout: no response to {cmd.strip()!r}", RuntimeWarning, stacklevel=2)

        return response

    def unlock(self):
        self._send_cmd("unlocked=1\r")

    def open(self, channel: int = 1):
        """Open the shutter."""
        self._send_cmd(f"enable{channel}=1\r")
    
    def close(self, channel: int = 1):
        """Close the shutter."""
        self._send_cmd(f"enable{channel}=0\r")
    
    def is_open(self, channel: int = 1) -> bool:
        """Check if the shutter is open."""
        command = f"enable{channel}?\r" if self.mode() == 'manual' else f"triggerstate{channel}?\r"
        response = self._send_cmd(command)
        
        # Fixed logic: explicitly look for a "1" to confirm it is open. 
        # If it times out (""), it will safely return False.
        if "1" in response:
            return True
        return False
    
    def is_closed(self, channel: int = 1) -> bool:
        """Check if the shutter is closed."""
        return not self.is_open(channel)
    
    def set_mode(self, mode: Literal['manual', 'internal']):
        if mode not in ['manual', 'internal']:
            raise ValueError("Only 'manual' and 'internal' are supported")
        
        if mode == 'manual':
            self._send_cmd("mode=0\r")
        elif mode == 'internal':
            self._send_cmd("mode=2\r")
            
        # Re-unlocking after mode change, as in your original logic
        self.unlock()

    def mode(self) -> Literal['manual', 'internal']:
        response = self._send_cmd("mode?\r")
        if "0" in response:
            return 'manual'
        elif "2" in response:
            return 'internal'
            
        print(f"Warning: Unknown mode response '{response}'")
        return 'manual' # Safe fallback

    def set_freq(self, freq: float, channel: int = 1):
        if not (0.1 <= freq <= 50.0):
            raise ValueError("Frequency must be between [0.1, 50.0]")
        self._send_cmd(f"intfreq{channel}={freq}\r")

    def __del__(self):
        # Safely attempt to close hardware on deletion, skipping if it fails
        if hasattr(self, 'ser') and self.ser.is_open:
            try:
                self.close()
                self.ser.close()
            except Exception:
                pass