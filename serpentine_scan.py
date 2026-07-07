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
    print("=" * 40)
    print("Initiating serpentine scan ...")
    stage = laserlab.ProScanStage(port="COM3")
    stage.position
    shutter = laserlab.SC30Shutter(port="COM6")
    shutter.set_mode('manual')
    shutter.close()
    
    print("=" * 40)
    
    # ---------------------------------------------------------
    # 1. ROI DEFINITION & SAVING
    # ---------------------------------------------------------
    print("Select ROI Method:")
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
            # Save the vertices to your local directory for next time
            np.save("roi_vertices.npy", vertices)
            print("Rectangle generated and saved to 'roi_vertices.npy' successfully.")
        except ValueError as e:
            print(f"Error: {e}")
            return # Safely exit if the area is zero
    
    polygon = Polygon(vertices)
    if (not polygon.is_valid) or polygon.area <= 0:
        raise ValueError("Invalid polygon. Please ensure vertices define one closed area.")
    
    # ---------------------------------------------------------
    # 2. SERPENTINE PATH GENERATION WITH PRE-LOAD SETTINGS
    # ---------------------------------------------------------
    print("Choose Serpentine Path Settings Method:")
    print("1. Previous settings (if available)")
    print("2. Define new settings manually")
    
    settings_choice = ""
    while settings_choice not in ["1", "2"]:
        settings_choice = input("Enter choice (1 or 2): ").strip()
    
    if settings_choice == "1" and os.path.exists("serpentine_settings.npy"):
        settings = np.load("serpentine_settings.npy", allow_pickle=True).item()
        # Fallback to old 'y_step_um' key if 'step_um' isn't found
        step_um = settings.get("step_um", settings.get("y_step_um"))
        sweep_time = settings.get("sweep_time")
        direction = settings.get("direction", "horizontal")
        
        print(f"Loaded previous settings: direction = {direction}")
        print(f"Loaded previous settings: step_um = {step_um} um")
        print(f"Loaded previous settings: sweep_time = {sweep_time} s")
    else:
        if settings_choice == "1":
            print("No saved settings found. Defaulting to new setup.")
            
        direction_choice = ""
        while direction_choice not in ["1", "2"]:
            direction_choice = input("Select scan direction (1: Horizontal, 2: Vertical): ").strip()
        direction = "horizontal" if direction_choice == "1" else "vertical"
        
        step_um = float(input(f"Enter the desired distance between {direction} scan lines (um): "))
        sweep_time_str = input(f"Enter the time (in seconds) it should take to sweep one {direction} line: ")
        try:
            sweep_time = float(sweep_time_str)
            if sweep_time <= 0:
                raise ValueError("Sweep time must be greater than 0.")
        except ValueError as e:
            print(f"Invalid time: {e}")
            return
            
        np.save("serpentine_settings.npy", {"step_um": step_um, "sweep_time": sweep_time, "direction": direction})
        print("Settings saved to 'serpentine_settings.npy' successfully.")
        
    step_steps = step_um * stage.steps_per_micron
    
    # Pass the direction variable into the generation function
    scan_points = generate_rectangle_serpentine_path_smooth(polygon.bounds, step=step_steps, direction=direction)
    print(f"Generated {len(scan_points)} scan points.")
    
    # Dynamically calculate physical distance based on direction
    min_x, min_y, max_x, max_y = polygon.bounds
    if direction == 'horizontal':
        sweep_distance_steps = max_x - min_x
    else:
        sweep_distance_steps = max_y - min_y
        
    sweep_distance_um = sweep_distance_steps / stage.steps_per_micron
    
    # Calculate required velocity (microns / second)
    velocity_um_s = sweep_distance_um / sweep_time
    print(f"Calculated sweep line distance: {sweep_distance_um:.2f} um")
    print(f"Setting stage velocity to {velocity_um_s:.2f} um/s to achieve a {sweep_time}s sweep.")
                
    # Command the hardware
    stage.set_velocity(velocity_um_s)
        
    # ---------------------------------------------------------
    # 3. VISUALIZATION & DATA SAVING
    # ---------------------------------------------------------
    vertices_mm = vertices / (1000 * stage.steps_per_micron)
    scan_points_mm = scan_points / (1000 * stage.steps_per_micron)

    # Visualize the defined polygon
    fig, ax = plt.subplots()
    ax.plot(vertices_mm[:, 0], vertices_mm[:, 1], 'ro-')
    ax.set_title(f"Defined Polygon ({direction.capitalize()} Scan)")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.fill(vertices_mm[:, 0], vertices_mm[:, 1], alpha=0.3)
    if len(scan_points_mm) > 0:
        ax.plot(scan_points_mm[:, 0], scan_points_mm[:, 1], 'b.-', lw=0.8, ms=2)
        ax.scatter(scan_points_mm[0, 0], scan_points_mm[0, 1], c='g', s=40, label='Start')
        ax.scatter(scan_points_mm[-1, 0], scan_points_mm[-1, 1], c='k', s=40, label='End')
        ax.legend()
        
    plt.show() # 1. Show the serpentine path generated
    plt.close(fig)

    save_choice = input("Save scan points to 'scan_points.csv'? (y/n): ")
    if save_choice.lower() == 'y':
        np.savetxt("scan_points.csv", scan_points, delimiter=",", header="x_steps,y_steps", comments="")
        print("Scan points saved to 'scan_points.csv'.")
    else:
        print("Scan points not saved.")

    interval_ms=0
    # ---------------------------------------------------------
    # 4. MANUAL IMAGING PREP & HARDWARE EXECUTION
    # ---------------------------------------------------------
    print("\n--- Manual Pre-Scan Imaging ---")
    
    # 1. Close shutter automatically just in case
    if shutter.is_open():
        shutter.close()
        print("Shutter closed for safety.")
    
    # 2. Add an explicit pause to ensure physical safety
    input("WARNING: Please ensure the laser is TURNED OFF or physically blocked manually. Press Enter when confirmed...")
    
    # 3. Go to the center of the ROI
    print("Moving stage to the CENTER of the ROI for imaging...")
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    stage.move_to(center_x, center_y)
    
    # 4. Ask the user to take a picture
    input("Stage is centered on the ROI. Please take your pre-scan picture manually now. Press Enter when done...")
    
    # 5. Move to the actual start point of the scan
    print("Moving stage to the starting position of the scan...")
    stage.move_to(*scan_points[0])
    
    # 6. The "Arming" phase - explicit confirmation before firing
    print("\n--- READY TO SCAN ---")
    input("Stage is in position. Please TURN ON the laser manually. Press Enter when you are ready to open the shutter and begin...")
    
    # 7. Run the path safely
    print("Starting scan...")
    try:
        shutter.open()
        stage.scan(scan_points, interval_ms)  
    finally:
        # The 'finally' block guarantees the shutter closes even if you hit Ctrl+C or the stage disconnects!
        shutter.close()
        print("Shutter safely closed.")
        
    print("Scan completed.")
    print('Serpentine scan finished. You may now safely exit the program.')
    print("=" * 40)

if __name__ == "__main__":
    main()