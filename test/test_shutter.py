import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import laserlab
import time

if __name__ == "__main__":
    interval = 0.5
    shutter = laserlab.SC30Shutter("COM6")
    time.sleep(interval)
    for _ in range(3):
        shutter.open()
        time.sleep(interval)
        shutter.close()
        time.sleep(interval)

    shutter.set_mode('internal')
    shutter.set_freq(50)
    shutter.open()
    time.sleep(3)
