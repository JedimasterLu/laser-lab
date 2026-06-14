'''
This program select a line and a specific time to scan along it.
Author: Junyuan Lu
Email: lu1301@purdue.edu
'''
import numpy as np
import laserlab

def main():
    print("=" * 40)
    print("Initiating line scan ...")
    stage = laserlab.ProScanStage(port="COM3")
    stage.position
    shutter = laserlab.SC30Shutter(port="COM6")
    shutter.set_mode('manual')
    shutter.close()
    print("=" * 40)
    print("Please define the line endpoints:")
    print("Enter 'a' to add a point.")
    print("Please use the joystick to move to the desired" \
        "position before pressing 'a'.")

    points = []
    new_input = ""
    for _ in range(2):
        new_input = input("Enter command: ")
        if new_input == "a":
            points.append(stage.position)
            print(f"Position added: {stage.position}, total points: {len(points)}")
        else:
            print("Invalid command. Please enter 'a'.")

    scan_time = float(input("Please enter the scan time in seconds: "))

    speed = np.linalg.norm(np.array(points[1]) - np.array(points[0])) / stage.steps_per_micron / scan_time
    print(f"Calculated speed: {speed:.2f} µm/s")

    print("Running line scan.")
    shutter.close()
    stage.move_to(*points[0])
    print(f"Currently at point #1 {points[0]}")
    # Set the speed of the stage
    stage.set_velocity(float(speed))
    print(f"Stage velocity set to {stage.velocity:.2f} µm/s")

    shutter.open()
    stage.move_to(*points[1])
    print(f"Currently at point #2 {points[1]}")
    shutter.close()

    # Reset speed to default: 100 intrinsic units/s
    stage.set_velocity(100 / stage.steps_per_micron)

    print('Line scan finished. You may now safely exit the program.')
    print("=" * 40)
