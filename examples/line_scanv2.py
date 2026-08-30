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
    stage.set_velocity(100)
    print("=" * 40)
    print("Please define the line endpoints:")
    print("Enter 'a' to add a point.")
    print("Please use the joystick to move to the desired " \
        "position before pressing 'a'.")
    print("")

    points = []
    new_input = ""
    new_input = input("Enter command: ")
    if new_input == "a":
        points.append(stage.position)
        print(f"Position added: {stage.position}, total points: {len(points)}")
    else:
        raise ValueError("Invalid command. Please enter 'a' to add a point.")

    direction = float(input("Please enter the direction of the line in degrees (0-360): "))
    distance = float(input("Please enter the distance to scan in microns: "))

    scan_time = float(input("Please enter the scan time in seconds: "))
    distance = distance * stage.steps_per_micron  # Convert distance to steps
    points.append((points[0][0] + distance * -np.cos(np.radians(direction + 90)),
                   points[0][1] + distance * np.sin(np.radians(direction + 90))))
    speed = float(np.linalg.norm(np.array(points[1]) - np.array(points[0])) / stage.steps_per_micron / scan_time)
    print(f"Calculated speed: {speed:.4f} µm/s")

    try:
        print()
        print("Running line scan.")
        # shutter.close()
        # stage.move_to(*points[0])
        print(f"Currently at point #0 {points[0]}")
        # Set the speed of the stage
        stage.set_velocity(speed)
        print(f"Stage velocity set to {stage.velocity:.4f} µm/s")
        print(f"ETA: {np.linalg.norm(np.array(points[0]) - np.array(points[1])) / stage.steps_per_micron / stage.velocity} sec")
        print("Press Ctrl+C to interrupt")

        stage.move_to(*points[1])
        print(f"Currently at point #1 {points[1]}")

        print()
        stage.set_velocity(100)

        print('Line scan finished. You may now safely exit the program.')
        print("=" * 40)
        stage.close()
    
    except KeyboardInterrupt:
        print()
        print("Keyboard interrupted!")
        print("Stopping the current scan ...")
        stage.close()
        print('You may now safely exit the program.')
        print("=" * 40)
    finally:
        stage.close()

if __name__ == '__main__':
    main()
