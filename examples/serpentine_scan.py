import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Polygon
import os
import json
import time
import cv2
import laserlab

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

def main_pipeline():
    print("=== PUF Laser Automation Pipeline ===")
    
    # ---------------------------------------------------------
    # 0. INITIALIZE HARDWARE 
    # ---------------------------------------------------------
    stage_port = "COM3"  # Replace with actual COM port
    shutter_port = "COM4" # Replace with actual COM port
    
    # stage = ProScanStage(port=stage_port)
    # shutter = SC30Shutter(port=shutter_port)
    camera = None

    # ---------------------------------------------------------
    # 1. REGION SELECTION (3-Way Branch)
    # ---------------------------------------------------------
    print("\n--- 1. Region Selection ---")
    print("Select an option:")
    print("  [0] Pre-load an existing ROI ('roi_vertices.npy')")
    print("  [1] Draw boundaries manually (2 diagonal corners)")
    print("  [2] Input square dimensions (1 reference corner + side length)")
    
    method = input("Enter your choice (0, 1, or 2): ").strip()
    
    if method == "0":
        try:
            vertices = np.load("roi_vertices.npy")
            print("Successfully loaded existing 'roi_vertices.npy'.")
        except FileNotFoundError:
            print("Error: 'roi_vertices.npy' not found. Please run option 1 or 2 first.")
            return

    elif method == "1":
        print("\nUse the joystick to move to the first corner, then press 'a'.")
        print("Move to the opposite diagonal corner and press 'a' again.")
        diagonal_points = []
        while len(diagonal_points) < 2:
            new_input = input("Enter command ('a' to add point): ").strip().lower()
            if new_input == "a":
                diagonal_points.append(stage.position)
                print(f"Corner {len(diagonal_points)} added: {stage.position}")
            else:
                print("Invalid command. Please enter 'a'.")
        
        vertices = generate_rectangle_vertices(diagonal_points[0], diagonal_points[1])
        np.save("roi_vertices.npy", vertices)
        print("ROI generated and saved to 'roi_vertices.npy'.")

    elif method == "2":
        print("\nUse the joystick to move to the reference corner, then press 'a'.")    
        reference_point = None
        while reference_point is None:
            new_input = input("Enter command ('a' to add point): ").strip().lower()
            if new_input == "a":
                reference_point = stage.position
                print(f"Reference corner added: {reference_point}")
            else:
                print("Invalid command. Please enter 'a'.")
                
        side_length_um = float(input("Enter the side length of the square in microns: "))
        side_length_steps = side_length_um * stage.steps_per_micron # Assuming steps_per_micron is accessible
        vert_rel_position = input("Specify the position of the reference corner relative to the square (bottom-left, bottom-right, top-left, top-right): ").strip().lower()
        
        vertices = generate_rectangle_vertices_with_point_and_diagonal_length(reference_point, side_length_steps, vert_rel_position)
        np.save("roi_vertices.npy", vertices)
        print("Square generated and saved to 'roi_vertices.npy'.")
        
    else:
        print("Invalid selection. Exiting.")
        return

    # Create Polygon and calculate bounds for later
    roi_polygon = Polygon(vertices)
    min_x, min_y, max_x, max_y = roi_polygon.bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    print("ROI Polygon successfully established.")


    # ---------------------------------------------------------
    # 2. ROUTINE DEVELOPMENT (Complex Dictionary)
    # ---------------------------------------------------------
    print("\n--- 2. Routine Configuration ---")
    routine_dictionary = []
    
    print("Build your testing routine. You can stack multiple scanning phases.")
    phase_count = 1
    
    while True:
        print(f"\n--- Phase {phase_count} ---")
        orientation = input("Scan direction ('h' for horizontal, 'v' for vertical): ").strip().lower()
        orientation_str = "horizontal" if orientation == 'h' else "vertical"
        
        step_um = float(input("Enter the step size (distance between lines) in microns: "))
        sweep_time = float(input("Enter the desired sweep time per line in seconds: "))
        iterations = int(input(f"How many times should the {orientation_str} scan run? "))
        
        # Calculate Required Velocity for this specific phase
        # If horizontal, we traverse the X width. If vertical, we traverse the Y height.
        # (Assuming you have stage.steps_per_micron available)
        if orientation_str == "horizontal":
            sweep_distance_um = (max_x - min_x) / stage.steps_per_micron
        else:
            sweep_distance_um = (max_y - min_y) / stage.steps_per_micron
            
        velocity_um_s = sweep_distance_um / sweep_time

        # Append to our master dictionary
        phase_config = {
            "phase": phase_count,
            "orientation": orientation_str,
            "step_um": step_um,
            "sweep_time_s": sweep_time,
            "velocity_um_s": velocity_um_s,
            "iterations": iterations
        }
        routine_dictionary.append(phase_config)
        
        more = input("Add another phase to this routine? (y/n): ").strip().lower()
        if more != 'y':
            break
        phase_count += 1

    # Save dictionary as a JSON file so it is human-readable later
    with open("routine_config.json", "w") as f:
        json.dump(routine_dictionary, f, indent=4)
    print("\nRoutine saved to 'routine_config.json'.")


    # ---------------------------------------------------------
    # 3. CAMERA AUTOMATION PROMPT
    # ---------------------------------------------------------
    print("\n--- 3. Camera Mode Selection ---")
    auto_cam_choice = input("Do you want to automate camera image captures? (y/n): ").strip().lower()
    
    if auto_cam_choice == 'y':
        print("Initializing Nikon camera...")
        dll_path = r"C:\Program Files\Nikon\DSCam\DSCam.dll" 
        try:
            camera = NikonDSFi3Camera(dll_path=dll_path)
            camera.set_exposure(0.1) # 100ms default
            print("Camera successfully linked.")
        except Exception as e:
            print(f"Failed to initialize camera: {e}\nFalling back to manual camera mode.")
            camera = None

    os.makedirs("PUF_Runs", exist_ok=True)

    # ---------------------------------------------------------
    # 4. EXECUTION LOOP
    # ---------------------------------------------------------
    print("\n--- 4. Beginning Execution Loop ---")
    
    global_run_counter = 1
    total_runs = sum(phase["iterations"] for phase in routine_dictionary)

    for phase in routine_dictionary:
        print(f"\n================ STARTING PHASE {phase['phase']} ({phase['orientation'].upper()}) ================")
        
        # 4a. Generate the path just once for this specific phase
        step_steps = phase["step_um"] * stage.steps_per_micron
        
        # Assuming your path generation function takes 'direction' as an argument now
        scan_points = generate_serpentine_path(roi_polygon, step_steps, direction=phase["orientation"])
        
        # 4b. Execute iterations for this phase
        for i in range(phase["iterations"]):
            print(f"\n--- RUN {global_run_counter}/{total_runs} [Phase {phase['phase']}: {i+1}/{phase['iterations']}] ---")
            
            # PRE-SCAN IMAGING
            print("Moving to center for Pre-Scan Image...")
            stage.move_to(center_x, center_y)
            time.sleep(0.5) 
            
            if camera:
                img = camera.get_image()
                cv2.imwrite(f"PUF_Runs/Run_{global_run_counter}_Before.tif", img)
            else:
                input("MANUAL MODE: Please capture the Pre-Scan image, then press Enter...")

            # HARDWARE EXECUTION
            print("Moving to scan start position...")
            stage.move_to(scan_points[0][0], scan_points[0][1])
            time.sleep(0.5)
            
            # Set the calculated velocity for this specific phase
            stage.set_velocity(phase["velocity_um_s"])
            
            #input("SAFETY: Turn ON the physical laser switch. Press Enter when ready...")
            
            try:
                print(f"Executing {phase['orientation']} scan at {phase['velocity_um_s']:.2f} um/s...")
                shutter.open()
                stage.scan(scan_points) 
            finally:
                shutter.close()
                print("Scan complete. Shutter closed.")
                
            #input("SAFETY: Turn OFF the physical laser switch. Press Enter when ready...")

            # POST-SCAN IMAGING
            print("Moving to center for Post-Scan Image...")
            stage.move_to(center_x, center_y)
            time.sleep(0.5)
            
            if camera:
                img = camera.get_image()
                cv2.imwrite(f"PUF_Runs/Run_{global_run_counter}_After.tif", img)
            else:
                input("MANUAL MODE: Please capture the Post-Scan image, then press Enter...")
                
            global_run_counter += 1
            
    print("\n=== All Phases Complete! ===")
    if camera:
        camera.close()

if __name__ == "__main__":
    main_pipeline()