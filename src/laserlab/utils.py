from serial.tools import list_ports

def print_ports():
    ports = list_ports.comports()

    for port in ports:
        print("Device:", port.device)
        print("Serial Number:", port.serial_number)
