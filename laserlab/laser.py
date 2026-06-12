import serial

class LaserControl:
    def __init__(self, port: str, baudrate: int = 115200):
        """The generic Laser control instance via Serial.

        Args:
            port (str): The port name (e.g., 'COM4').
            baudrate (int): The baud rate for the specific laser model.
        """
        self.ser = serial.Serial(port, baudrate=baudrate, timeout=1)
        
        # Optional: Wake up or unlock the laser on initialization
        # self.unlock()

    def unlock(self):
        """Unlock or initialize the laser for remote control."""
        # Replace 'system:unlock' with your laser's specific command
        self.ser.write(b"system:unlock\r")
        self.ser.read_until(b">").decode().strip()

    def enable_emission(self, state: bool):
        """Turn the laser emission ON (True) or OFF (False)."""
        # Replace 'emission=1' with your laser's specific command
        command = b"emission=1\r" if state else b"emission=0\r"
        self.ser.write(command)
        self.ser.read_until(b">").decode().strip()

    def set_power(self, power: float):
        """Set the output power of the laser.

        Args:
            power (float): Desired power in milliwatts (mW) or percentage,
                           depending on your laser's requirements.
        """
        if power < 0:
            raise ValueError("Laser power cannot be negative.")
            
        # Replace 'power=' with your laser's specific syntax
        command = f"power={power}\r".encode()
        self.ser.write(command)
        self.ser.read_until(b">").decode().strip()

    def get_power(self) -> float:
        """Read the current power setting of the laser."""
        # Replace 'power?' with your laser's specific query command
        self.ser.write(b"power?\r")
        response = self.ser.read_until(b">").decode().strip()
        
        # Parse the response to extract the float value.
        # This assumes a response like "power=2.5>". You will need to 
        # tweak the string slicing based on what your laser spits back.
        try:
            clean_response = response.replace("power=", "").replace(">", "").strip()
            return float(clean_response)
        except ValueError:
            raise ValueError(f"Unexpected response from laser hardware: {response}")

    def close(self):
        """Safely shut down the laser and close the serial port."""
        self.enable_emission(False) # Hardware failsafe: ensure laser is off
        self.ser.close()