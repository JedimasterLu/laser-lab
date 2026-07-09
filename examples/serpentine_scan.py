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
            side_length = float(input("Enter the side length of the square in microns: "))
            vert_rel_position = input("Specify the position of the reference corner relative to the square (bottom-left, bottom-right, top-left, top-right): ").strip().lower()
            
            vertices = generate_rectangle_vertices_with_point_and_diagonal_length(stage.position, side_length, vert_rel_position)
            np.save("roi_vertices.npy", vertices)
            print("Square generated and saved to 'roi_vertices.npy' successfully.")
            
    polygon = Polygon(vertices)
    if (not polygon.is_valid) or polygon.area <= 0:
        raise ValueError("Invalid polygon. Please ensure vertices define one closed area.")
    
    min_x, min_y, max_x, max_y = polygon.bounds

    # ---------------------------------------------------------
    # 2. BATCH SCHEDULE BUILDER
    # ---------------------------------------------------------
    print("\n" + "=" * 60)
    print("SCAN SCHEDULE CONFIGURATION")
    print("=" * 60)
    
    while True:
        try:
            num_settings = int(input("How many DIFFERENT combinations of step-size, direction, and sweep-time do you want to run? "))
            if num_settings > 0:
                break
        except ValueError:
            print("Please enter a valid number.")

    scan_schedule = []

    for i in range(num_settings):
        print(f"\n--- Configuration {i+1} of {num_settings} ---")
        
        dir_choice = ""
        while dir_choice not in ["1", "2"]:
            dir_choice = input("Select scan direction (1: Horizontal, 2: Vertical): ").strip()
        direction = "horizontal" if dir_choice == "1" else "vertical"
        
        while True:
            try:
                step_um = float(input(f"Enter distance between {direction} scan lines (um): "))
                sweep_time = float(input(f"Enter time to sweep one {direction} line (s): "))
                if sweep_time <= 0 or step_um <= 0:
                    raise ValueError("Values must be greater than 0.")
                break
            except ValueError as e:
                print(f"Invalid input: {e}. Try again.")

        while True:
            try:
                num_runs = int(input(f"How many iterations (runs) for Configuration {i+1}? "))
                if num_runs > 0:
                    break
            except ValueError:
                print("Please enter a valid number.")
                
        scan_schedule.append({
            "config_num": i + 1,
            "direction": direction,
            "step_um": step_um,
            "sweep_time": sweep_time,
            "iterations": num_runs
        })

    # Save the schedule in case you need to review what you ran later
    np.save("last_scan_schedule.npy", scan_schedule)
    
    total_runs = sum(config["iterations"] for config in scan_schedule)
    print(f"\nTotal runs scheduled across all configurations: {total_runs}")

    # ---------------------------------------------------------
    # 3. MASTER EXECUTION LOOP
    # ---------------------------------------------------------
    interval_ms = 0
    run_counter = 1
    
    for config in scan_schedule:
        print("\n" + "=" * 60)
        print(f"INITIALIZING CONFIGURATION {config['config_num']}")
        print(f"Settings: {config['direction'].capitalize()} | Step: {config['step_um']}um | Time: {config['sweep_time']}s | Runs: {config['iterations']}")
        print("=" * 60)
        
        # --- Generate Path for Current Config ---
        step_steps = config['step_um'] * stage.steps_per_micron
        scan_points = generate_rectangle_serpentine_path_smooth(polygon.bounds, step=step_steps, direction=config['direction'])
        
        # --- Calculate Velocity for Current Config ---
        if config['direction'] == 'horizontal':
            sweep_distance_steps = max_x - min_x
        else:
            sweep_distance_steps = max_y - min_y
            
        sweep_distance_um = sweep_distance_steps / stage.steps_per_micron
        velocity_um_s = sweep_distance_um / config['sweep_time']
        
        print(f"Generated {len(scan_points)} scan points.")
        print(f"Calculated sweep line distance: {sweep_distance_um:.2f} um")
        print(f"Setting stage velocity to {velocity_um_s:.2f} um/s.")
        
        stage.set_velocity(velocity_um_s)
        
        # --- Visualization & Saving (Once per config) ---
        vertices_mm = vertices / (1000 * stage.steps_per_micron)
        scan_points_mm = scan_points / (1000 * stage.steps_per_micron)

        fig, ax = plt.subplots()
        ax.plot(vertices_mm[:, 0], vertices_mm[:, 1], 'ro-')
        ax.set_title(f"Config {config['config_num']}: {config['direction'].capitalize()} Scan")
        ax.set_xlabel("X (mm)")
        ax.set_ylabel("Y (mm)")
        ax.fill(vertices_mm[:, 0], vertices_mm[:, 1], alpha=0.3)
        if len(scan_points_mm) > 0:
            ax.plot(scan_points_mm[:, 0], scan_points_mm[:, 1], 'b.-', lw=0.8, ms=2)
            ax.scatter(scan_points_mm[0, 0], scan_points_mm[0, 1], c='g', s=40, label='Start')
            ax.scatter(scan_points_mm[-1, 0], scan_points_mm[-1, 1], c='k', s=40, label='End')
            ax.legend()
            
        print("Plotting path... Close the window to proceed with the hardware execution.")
        plt.show() 
        plt.close(fig)

        save_choice = input(f"Save scan points for Config {config['config_num']} to CSV? (y/n): ")
        if save_choice.lower() == 'y':
            filename = f"scan_points_config_{config['config_num']}.csv"
            np.savetxt(filename, scan_points, delimiter=",", header="x_steps,y_steps", comments="")
            print(f"Saved to '{filename}'.")

        # --- Execute Iterations for Current Config ---
        for iteration in range(config['iterations']):
            print(f"\n--- RUN {run_counter}/{total_runs} (Iteration {iteration+1} of Config {config['config_num']}) ---")
            
            # 1. Shutter Safety Check
            if shutter.is_open():
                shutter.close()
            
            # 2. Laser Off / Blocked Confirmation
            #input("WARNING: Ensure laser is TURNED OFF manually. Press Enter when confirmed...")
            
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
            #input(f"Stage in position for Run {run_counter}. TURN ON laser manually. Press Enter to begin...")
            
            print("Scanning...")
            try:
                shutter.open()
                stage.scan(scan_points, interval_ms)  
            finally:
                shutter.close()
                print("Shutter safely closed.")
                
            print(f"Run {run_counter} completed.")
            
            # 6. Post-Scan Image / Pause before next iteration
            print("Moving back to ROI center for post-scan imaging...")
            stage.move_to(center_x, center_y)
            input("Stage centered. Take post-scan picture if needed. Press Enter to continue to the next run...")
            
            run_counter += 1

    print("\n" + "=" * 60)
    print("ALL SCHEDULED RUNS COMPLETED SUCCESSFULLY.")
    print("=" * 60)

if __name__ == "__main__":
    main()