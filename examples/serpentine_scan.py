import numpy as np
import matplotlib.pyplot as plt
import laserlab
from shapely.geometry import Polygon
import os

def generate_rectangle_vertices(p1: tuple[float, float], p2: tuple[float, float]) -> np.ndarray:
    """
    Generate the 4 vertices of a rectangle given two opposite diagonal corners.
    Returns the vertices in a sequential order to form a valid polygon.
    """
    x1, y1 = p1
    x2, y2 = p2
    
    # Calculate the bounding box coordinates
    min_x, max_x = min(x1, x2), max(x1, x2)
    min_y, max_y = min(y1, y2), max(y1, y2)
    
    area = (max_x - min_x) * (max_y - min_y)
    if area <= 0:
        raise ValueError("The provided points do not form a valid rectangle (zero area).")
    
    # Define the 4 corners in order (e.g., bottom-left, bottom-right, top-right, top-left)
    vertices = [
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y)
    ]
    
    return np.array(vertices)

def generate_rectangle_vertices_with_point_and_diagonal_length(p1: tuple[float, float], square_side_length: float, rel_pos: str) -> np.ndarray:
    """
    Generate square bounding vertices using one given point, its position relative to the rest of the square, and the 
    side length. The function calculates the other three vertices based on the provided point and side length.
    
    Args:
        p1 (tuple[float, float]): The reference coordinate (x, y).
        square_side_length (float): The length of the sides of the square.
        rel_pos (str): Position of p1. Options: 'bottom-left', 'bottom-right', 'top-left', 'top-right'.

    Returns:
        np.ndarray: A 4x2 array of vertices in sequential order (bottom-left, bottom-right, top-right, top-left) 
                    to form a valid polygon.
    """
    x1, y1 = p1
    side = square_side_length
    
    # Standardize the input string to prevent capitalization/spacing errors
    rel_pos = rel_pos.lower().strip()
    
    # Calculate min and max bounds based on where the reference point is
    if rel_pos == 'bottom-left':
        min_x, min_y = x1, y1
        max_x, max_y = x1 + side, y1 + side
    elif rel_pos == 'bottom-right':
        max_x, min_y = x1, y1
        min_x, max_y = x1 - side, y1 + side
    elif rel_pos == 'top-left':
        min_x, max_y = x1, y1
        max_x, min_y = x1 + side, y1 - side
    elif rel_pos == 'top-right':
        max_x, max_y = x1, y1
        min_x, min_y = x1 - side, y1 - side
    else:
        raise ValueError("rel_pos must be 'bottom-left', 'bottom-right', 'top-left', or 'top-right'")
        
    # Return vertices sequentially to form a valid polygon
    vertices = np.array([
        [min_x, min_y],  # Bottom-Left
        [max_x, min_y],  # Bottom-Right
        [max_x, max_y],  # Top-Right
        [min_x, max_y]   # Top-Left
    ])
    
    return vertices
    
def generate_rectangle_serpentine_path_smooth(bounds: tuple, step: float, direction: str = 'horizontal') -> np.ndarray:
    """
    Generate smooth serpentine points using only row/column endpoints.
    
    Args:
        bounds (tuple): (min_x, min_y, max_x, max_y)
        step (float): The distance between each scan line in stage steps.
        direction (str): 'horizontal' or 'vertical'.
    """
    min_x, min_y, max_x, max_y = bounds
    
    if direction == 'horizontal':
        y_values = np.arange(min_y, max_y + step, step)
        x_values = np.array([min_x, max_x])
        
        X, Y = np.meshgrid(x_values, y_values)
        X[1::2, :] = X[1::2, ::-1]
        return np.column_stack((X.ravel(), Y.ravel()))
        
    elif direction == 'vertical':
        x_values = np.arange(min_x, max_x + step, step)
        y_values = np.array([min_y, max_y])
        
        X, Y = np.meshgrid(x_values, y_values)
        X_t, Y_t = X.T, Y.T
        Y_t[1::2, :] = Y_t[1::2, ::-1]
        return np.column_stack((X_t.ravel(), Y_t.ravel()))
        
    else:
        raise ValueError("Direction must be either 'horizontal' or 'vertical'.")

def main():
    print("=" * 60)
    print("Initiating Batch Serpentine Scan Controller...")
    print("=" * 60)
    
    # ---------------------------------------------------------
    # 0. HARDWARE INITIALIZATION
    # ---------------------------------------------------------
    stage = laserlab.ProScanStage(port="COM3")
    stage.position
    shutter = laserlab.SC30Shutter(port="COM6")
    shutter.set_mode('manual')
    shutter.close()
    
    # ---------------------------------------------------------
    # 1. ROI DEFINITION
    # ---------------------------------------------------------
    print("\nSelect ROI Method:")
    print(" 1: Define NEW rectangle using joystick")
    print(" 2: Load PREVIOUS rectangle from memory")
    
    roi_choice = ""
    while roi_choice not in ["1", "2"]:
        roi_choice = input("Enter choice (1 or 2): ").strip()
    
    vertices = None
    if roi_choice == "2" and os.path.exists("roi_vertices.npy"):
        vertices = np.load("roi_vertices.npy")
        print(f"Successfully loaded previous ROI with {len(vertices)} vertices.")
    else:
        if roi_choice == "2":
            print("No saved ROI found. Defaulting to new setup.")
            
        rectangle_method = ""
        while rectangle_method not in ["1", "2"]:
            print("\nSelect Rectangle Definition Method:")
            print(" 1: Define using two diagonal corners")
            print(" 2: Define using one corner and side length")
            rectangle_method = input("Enter choice (1 or 2): ").strip()
        
        if rectangle_method == "1":
            print("Use the joystick to move to the first corner, then press 'a'.")
            print("Move to the opposite diagonal corner and press 'a' again.")
                
            diagonal_points = []
            while len(diagonal_points) < 2:
                new_input = input("Enter command ('a' to add point): ").strip().lower()
                if new_input == "a":
                    diagonal_points.append(stage.position)
                    print(f"Corner {len(diagonal_points)} added: {stage.position}")
                else:
                    print("Invalid command. Please enter 'a'.")
            try:
                vertices = generate_rectangle_vertices(diagonal_points[0], diagonal_points[1])
                np.save("roi_vertices.npy", vertices)
                print("Rectangle generated and saved to 'roi_vertices.npy' successfully.")
            except ValueError as e:
                print(f"Error: {e}")
            return 
        else:
            print("Use the joystick to move to the reference corner, then press 'a'.")    
            reference_point = None
            while reference_point is None:
                new_input = input("Enter command ('a' to add point): ").strip().lower()
                if new_input == "a":
                    reference_point = stage.position
                    print(f"Reference corner added: {reference_point}")
                else:
                    print("Invalid command. Please enter 'a'.")
            # ----------------------------------------------------------------------
                    
            side_length_um = float(input("Enter the side length of the square in microns: "))
            side_length_steps = side_length_um * stage.steps_per_micron
            vert_rel_position = input("Specify the position of the reference corner relative to the square (bottom-left, bottom-right, top-left, top-right): ").strip().lower()
        
            # Replaced `stage.position` with the `reference_point` we just captured
            vertices = generate_rectangle_vertices_with_point_and_diagonal_length(reference_point, side_length_steps, vert_rel_position)
            np.save("roi_vertices.npy", vertices)
            print("Square generated and saved to 'roi_vertices.npy' successfully.")    
        
    polygon = Polygon(vertices)
    if (not polygon.is_valid) or polygon.area <= 0:
        raise ValueError("Invalid polygon. Please ensure vertices define one closed area.")
    
    min_x, min_y, max_x, max_y = polygon.bounds

    # ---------------------------------------------------------
    # 2. BATCH SCHEDULE BUILDER: LIBRARY & PHASES
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("STEP 1: DEFINE CONFIGURATION LIBRARY")
    print("=" * 60)
    
    config_library = {}
    
    while True:
        try:
            num_settings = int(input("How many UNIQUE configurations do you want to define? "))
            if num_settings > 0: break
        except ValueError:
            print("Please enter a valid number.")

    # BUILD THE LIBRARY
    for i in range(1, num_settings + 1):
        print(f"\n--- Defining Configuration ID: {i} ---")
        
        dir_choice = ""
        while dir_choice not in ["1", "2"]:
            dir_choice = input("Select scan direction (1: Horizontal, 2: Vertical): ").strip()
        direction = "horizontal" if dir_choice == "1" else "vertical"
        
        step_um = float(input(f"Enter distance between {direction} scan lines (um): "))
        sweep_time = float(input(f"Enter time to sweep one {direction} line (s): "))

        # Pre-calculate paths and velocities 
        step_steps = step_um * stage.steps_per_micron
        scan_points = generate_rectangle_serpentine_path_smooth(polygon.bounds, step=step_steps, direction=direction)
        
        sweep_distance_steps = (max_x - min_x) if direction == 'horizontal' else (max_y - min_y)
        velocity_um_s = (sweep_distance_steps / stage.steps_per_micron) / sweep_time

        # Save to library
        config_library[i] = {
            "id": i,
            "direction": direction,
            "step_um": step_um,
            "sweep_time": sweep_time,
            "velocity": velocity_um_s,
            "path": scan_points
        }
        
        print(f"Config {i} locked in. (Velocity: {velocity_um_s:.2f} um/s)")
        
        # --- Visualization & Saving (Moved here so it only happens ONCE per unique config) ---
        vertices_mm = vertices / (1000 * stage.steps_per_micron)
        scan_points_mm = scan_points / (1000 * stage.steps_per_micron)

        fig, ax = plt.subplots()
        ax.plot(vertices_mm[:, 0], vertices_mm[:, 1], 'ro-')
        ax.set_title(f"Config {i}: {direction.capitalize()} Scan")
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.fill(vertices_mm[:, 0], vertices_mm[:, 1], alpha=0.3)
        if len(scan_points_mm) > 0:
            ax.plot(scan_points_mm[:, 0], scan_points_mm[:, 1], 'b.-', lw=0.8, ms=2)
            ax.scatter(scan_points_mm[0, 0], scan_points_mm[0, 1], c='g', s=40, label='Start')
            ax.scatter(scan_points_mm[-1, 0], scan_points_mm[-1, 1], c='k', s=40, label='End')
            ax.legend()
            
        print("Plotting path... Close the window to proceed.")
        plt.show() 
        plt.close(fig)

        '''
        save_choice = input(f"Save scan points for Config {i} to CSV? (y/n): ")
        if save_choice.lower() == 'y':
            filename = f"scan_points_config_{i}.csv"
            np.savetxt(filename, scan_points, delimiter=",", header="x_steps,y_steps", comments="")
            print(f"Saved to '{filename}'.")
        '''
    # BUILD THE EXECUTION SCHEDULE
    print("\n" + "=" * 60)
    print("STEP 2: BUILD EXECUTION SCHEDULE")
    print("=" * 60)
    print("Available IDs:")
    for key, val in config_library.items():
        print(f"  ID {key}: {val['direction'].capitalize()} | {val['step_um']}um | {val['sweep_time']}s")

    scan_schedule = []

    print("\nSelect Scheduling Mode:")
    print("  1: Simple Sequence (Run configs in sequential order: 1, 2, 3...)")
    print("  2: Advanced Blocks (Build custom phases, alternations, and repeats)")
    
    while True:
        sched_mode = input("Enter choice (1 or 2): ").strip()
        if sched_mode in ["1", "2"]:
            break
            
    if sched_mode == "1":
        while True:
            try:
                repeats = int(input("How many times do you want to run this full sequence (1,2,3,... in that order, how many times)? "))
                if repeats > 0: break
            except ValueError:
                print("Please enter a valid number.")
                
        for _ in range(repeats):
            for c_id in config_library:
                scan_schedule.append(config_library[c_id])
                
    elif sched_mode == "2":
        while True:
            try:
                print("Here, you can define different combinations of the configuration settings in multiple phases.")
                num_phases = int(input("\nHow many execution phases (blocks) do you want to schedule?"))
                if num_phases > 0: break
            except ValueError:
                print("Please enter a valid number.")

        for phase in range(1, num_phases + 1):
            print(f"\n--- Phase {phase} ---")
            while True:
                print(f"Here, enter the combinations you want in the {phase} phase.")
                seq_input = input("Enter the Config IDs to run in sequence, separated by commas (e.g., '1,3' or '1,2,3'): ")
                try:
                    sequence = [int(x.strip()) for x in seq_input.split(',')]
                    if all(c_id in config_library for c_id in sequence):
                        break
                    else:
                        print(f"Error: Only use defined IDs: {list(config_library.keys())}")
                except ValueError:
                    print("Invalid format. Use numbers separated by commas.")

            while True:
                try:
                    repeats = int(input(f"How many times should the sequence {sequence} repeat? "))
                    if repeats > 0: break
                except ValueError:
                    print("Please enter a valid number.")

            # Ask for the repetition style if there are multiple items and multiple repeats
            if len(sequence) > 1 and repeats > 1:
                print("\nHow should these repeats be structured?")
                print("  1: Alternating (e.g., 1, 3, 1, 3, 1, 3)")
                print("  2: Blocked     (e.g., 1, 1, 1, 3, 3, 3)")
                while True:
                    rep_style = input("Enter choice (1 or 2): ").strip()
                    if rep_style in ["1", "2"]:
                        break
            else:
                rep_style = "1" # Defaults to 1 if it's just a single config anyway

            # Execute the chosen logic
            if rep_style == "1":
                # Alternating Loop (Iterate the sequence, then repeat)
                for _ in range(repeats):
                    for c_id in sequence:
                        scan_schedule.append(config_library[c_id])
            else:
                # Blocked Loop (Repeat each item fully before moving to the next)
                for c_id in sequence:
                    for _ in range(repeats):
                        scan_schedule.append(config_library[c_id])
                        
    total_runs = len(scan_schedule)
    print(f"\nTotal individual runs scheduled across all phases: {total_runs}")
    
    # ---------------------------------------------------------
    # 3. MASTER EXECUTION LOOP (FLATTENED)
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("INITIATING HARDWARE EXECUTION")
    print("=" * 60)
    
    interval_ms = 0
    
    for run_idx, current_run in enumerate(scan_schedule):
        c_id = current_run["id"]
        
        print(f"\n--- RUN {run_idx + 1}/{total_runs} (Using Config ID: {c_id}) ---")
        print(f"Settings: {current_run['direction'].capitalize()} | Step: {current_run['step_um']}um | Time: {current_run['sweep_time']}s")
        
        # --- Apply Pre-Calculated Hardware Settings ---
        stage.set_velocity(current_run["velocity"])
        scan_points = current_run["path"]
        
        # 1. Shutter Safety Check
        if shutter.is_open():
            shutter.close()
            
        # 3. Center for Pre-Scan Image
        print("Moving to ROI center...")
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        stage.move_to(center_x, center_y)
        
        input("Stage centered. Please take pre-scan picture now. Press Enter when done...")
        
        # 4. Move to Start Point
        print("Moving to scan starting position...")
        stage.move_to(*scan_points[0])
        
        # 5. Arm & Execute
        print("\n--- READY TO SCAN ---")
        print("Scanning...")
        try:
            shutter.open()
            stage.scan(scan_points, interval_ms)  
        finally:
            shutter.close()
            print("Shutter safely closed.")
            
        print(f"Run {run_idx + 1} completed.")
        
        # 6. Return to center
        print("Moving back to ROI center for post-scan imaging...")
        stage.move_to(center_x, center_y)
        input("Stage centered. Take post-scan picture. Press Enter to continue to the next run...")

    print("\n" + "=" * 60)
    print("ALL SCHEDULED RUNS COMPLETED SUCCESSFULLY.")
    print("=" * 60)

if __name__ == "__main__":
    main()