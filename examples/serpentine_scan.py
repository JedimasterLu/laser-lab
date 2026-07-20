import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import Polygon
import os
import json
import time
import cv2
import src # check this

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

def generate_angled_serpentine_path(bounds: tuple, step: float, angle_deg: float) -> np.ndarray:
    """
    Generate smooth serpentine points within a rectangular bounds at any angle.
    
    Args:
        bounds (tuple): (min_x, min_y, max_x, max_y)
        step (float): The distance between each scan line.
        angle_deg (float): Angle of the scan lines in degrees from the horizontal.
                           (e.g., 0 = horizontal, 90 = vertical, 45 = diagonal).
    """
    min_x, min_y, max_x, max_y = bounds
    theta = np.radians(angle_deg)
    
    # Unit vector normal (perpendicular) to the scan lines
    nx = -np.sin(theta)
    ny = np.cos(theta)
    
    # 4 corners of the bounding box
    corners = np.array([
        [min_x, min_y],
        [max_x, min_y],
        [max_x, max_y],
        [min_x, max_y]
    ])
    
    # Project the corners onto the normal vector to find the range of 'd'
    # 'd' represents the distance from the origin to each parallel scan line
    projections = corners[:, 0] * nx + corners[:, 1] * ny
    d_min, d_max = np.min(projections), np.max(projections)
    
    # Generate the steps along the normal vector
    d_values = np.arange(d_min, d_max + 1e-9, step)
    
    path = []
    left_to_right = True
    
    for d in d_values:
        intersections = []
        
        # 1. Find intersections with Left & Right edges (x = min_x, x = max_x)
        if abs(ny) > 1e-9: # Avoid division by zero if lines are perfectly vertical
            for x_edge in (min_x, max_x):
                y_edge = (d - nx * x_edge) / ny
                # Check if the intersection happens within the physical box
                if min_y - 1e-9 <= y_edge <= max_y + 1e-9:
                    intersections.append((x_edge, np.clip(y_edge, min_y, max_y)))
                    
        # 2. Find intersections with Top & Bottom edges (y = min_y, y = max_y)
        if abs(nx) > 1e-9: # Avoid division by zero if lines are perfectly horizontal
            for y_edge in (min_y, max_y):
                x_edge = (d - ny * y_edge) / nx
                if min_x - 1e-9 <= x_edge <= max_x + 1e-9:
                    intersections.append((np.clip(x_edge, min_x, max_x), y_edge))
        
        # Filter down to unique points (handles cases where a line perfectly clips a corner)
        unique_pts = []
        for pt in intersections:
            if not any(np.allclose(pt, u_pt, atol=1e-7) for u_pt in unique_pts):
                unique_pts.append(pt)
        
        # If we successfully found where the line enters and exits the ROI
        if len(unique_pts) >= 2:
            # Sort the points along the direction of the scan line
            dx, dy = np.cos(theta), np.sin(theta)
            unique_pts.sort(key=lambda p: p[0]*dx + p[1]*dy)
            
            pt1, pt2 = unique_pts[0], unique_pts[-1]
            
            # Alternate directions for the serpentine sweep
            if left_to_right:
                path.extend([pt1, pt2])
            else:
                path.extend([pt2, pt1])
                
            left_to_right = not left_to_right
            
    return np.array(path)

def visualize_angled_path(bounds: tuple, scan_points: np.ndarray, angle_deg: float):
    """
    Visualizes the generated serpentine path within the bounding box.
    Inverts the Y-axis to match camera/screen coordinates.
    """
    min_x, min_y, max_x, max_y = bounds
    
    plt.figure(figsize=(8, 6))
    
    # 1. Draw the bounding box (ROI)
    box_x = [min_x, max_x, max_x, min_x, min_x]
    box_y = [min_y, min_y, max_y, max_y, min_y]
    plt.plot(box_x, box_y, 'r--', label="ROI Boundary", linewidth=2)
    
    # 2. Draw the serpentine path
    plt.plot(scan_points[:, 0], scan_points[:, 1], 'b-', alpha=0.7, label=f"Laser Path ({angle_deg}°)")
    
    # 3. Highlight individual intersection points
    plt.scatter(scan_points[:, 0], scan_points[:, 1], c='blue', s=15, alpha=0.5)
    
    # 4. Highlight Start and End points explicitly for safety verification
    plt.scatter(scan_points[0, 0], scan_points[0, 1], c='green', s=150, marker='*', label='Start')
    plt.scatter(scan_points[-1, 0], scan_points[-1, 1], c='red', s=150, marker='X', label='End')
    
    # 5. Invert Y-Axis to match the CV camera screen coordinates
    plt.gca().invert_yaxis()
    
    # Formatting
    plt.title(f"Angled Serpentine Path Visualization ({angle_deg}°)")
    plt.xlabel("X (Stage Steps)")
    plt.ylabel("Y (Stage Steps) - Inverted for Screen")
    plt.legend(bbox_to_anchor=(1.04, 1), loc="upper left")
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.axis('equal') # Keep the aspect ratio square so angles visually look correct
    plt.tight_layout()
    
    print("Close the plot window to continue hardware execution...")
    plt.show()
    
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
        print("Note that the vertical axis is inverted - what appears to be the top right is actually bottom right")
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
        
        # Get the angle instead of H/V
        angle_input = input("Scan angle in degrees (e.g., 0 for horizontal, 90 for vertical, 45 for diagonal): ").strip()
        angle_deg = float(angle_input) if angle_input else 0.0
        
        step_um = float(input("Enter the step size (distance between lines) in microns: "))
        sweep_time = float(input("Enter the desired sweep time per longest line in seconds: "))
        iterations = int(input(f"How many times should the {angle_deg}° scan run? "))
        
        # Calculate Required Velocity for this specific phase
        # For an angled scan, we use the maximum diagonal distance to ensure safe, consistent velocity
        diag_distance_um = np.sqrt((max_x - min_x)**2 + (max_y - min_y)**2) / stage.steps_per_micron
            
        velocity_um_s = diag_distance_um / sweep_time

        # Append to our master dictionary
        phase_config = {
            "phase": phase_count,
            "angle_deg": angle_deg,
            "step_um": step_um,
            "sweep_time_s": sweep_time,
            "velocity_um_s": velocity_um_s,
            "iterations": iterations
        }
        routine_dictionary.append(phase_config)
        
        more = input("Add another phase to this routine? (y/n): ").strip().lower()
        if more != 'y':
            break
        else:
            phase_count += 1
            continue

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
        print(f"\n================ STARTING PHASE {phase['phase']} ({phase['angle_deg']}° ANGLE) ================")
        
        # 4a. Generate the path just once for this specific phase
        step_steps = phase["step_um"] * stage.steps_per_micron
        
        # Call the newly updated angled generation function
        bounds = (min_x, min_y, max_x, max_y)
        scan_points = generate_angled_serpentine_path(bounds, step_steps, phase["angle_deg"])
        
        # --- NEW: VISUALIZE THE PATH ---
        visualize_angled_path(bounds, scan_points, phase["angle_deg"])
        # -------------------------------
        
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
                print(f"Executing {phase['angle_deg']}° scan at {phase['velocity_um_s']:.2f} um/s...")
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