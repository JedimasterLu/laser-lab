import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

import laserlab

if __name__ == "__main__":

    stage = laserlab.ProScanStage("COM3")

    x, y = 40e5, 40e5
    stage.move_to(x, y)
    stage.wait()
    print(stage.position)

    dx = -1e5
    for i in range(5):
        stage.move_by(dx, 0)
        stage.wait()
        print(stage.position)

    x, y = 30e5, 30e5
    stage.move_to(x, y)
    stage.wait()
    print(stage.position)
    stage.close()