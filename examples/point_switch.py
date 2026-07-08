import laserlab
import matplotlib.pyplot as plt
import numpy as np

def main():
    print("=" * 40)
    print("Initiating point switch ...")
    stage = laserlab.ProScanStage(port="COM3")
    stage.position
    shutter = laserlab.SC30Shutter(port="COM6")
    shutter.set_mode('manual')
    shutter.close()
    print("=" * 40)
    print("Please define the switch positions:")
    print("Enter 'a' to add a point, 'q' to finish.")
    print("Please use the joystick to move to the desired" \
        "position before pressing 'a'.")

    points = []
    new_input = ""
    while new_input != "q":
        new_input = input("Enter command: ")
        if new_input == "a":
            points.append(stage.position)
            print(f"Position added: {stage.position}, total points: {len(points)}")
        elif new_input == "q":
            print("Finished defining positionsn.")
        else:
            print("Invalid command. Please enter 'a' or 'q'.")

    command = ''
    print("Running switch control. Enter 'q' to finish.")
    shutter.close()
    stage.move_to(*points[0])
    print(f"Currently at point #1 {points[0]}")
    current_point_index = 0
    print("The input format is [number][number].")
    print("The first number is the index of point, and the second is laser on/off (1/0).")
    while command not in ["Q", "q", "quit"]:
        command = input("> ")
        if command in ["Q", "q", "quit"]:
            break
        if len(command) == 1:
            laser_control = int(command[0])
            point_index = current_point_index
        else:
            laser_control = int(command[-1])
            point_index = int(command[:-1])
        if point_index != current_point_index:
            shutter.close()
            stage.move_to(*points[point_index])
            current_point_index = point_index
        if laser_control:
            shutter.open()
        else:
            shutter.close()

    print('Point switch finished. You may now safely exit the program.')
    print("=" * 40)

if __name__ == "__main__":
    main()
    