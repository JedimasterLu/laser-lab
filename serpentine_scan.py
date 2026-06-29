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

def generate_rectangle_serpentine_path_smooth(bounds: tuple, y_step: float) -> np.ndarray:
    """Generate smooth serpentine points using only row endpoints."""
    min_x, min_y, max_x, max_y = bounds
    
    # Generate the Y 'rungs' normally
    y_values = np.arange(min_y, max_y + y_step, y_step)
    
    # Only use the absolute start and end of the X bounds
    x_values = np.array([min_x, max_x])
    
    # Create the grids and flip the odd rows
    X, Y = np.meshgrid(x_values, y_values)
    X[1::2, :] = X[1::2, ::-1]
    
    return np.column_stack((X.ravel(), Y.ravel()))

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
    # 2. SMOOTH PATH & INTERVAL GENERATION
    # ---------------------------------------------------------
    print("\n--- Generating Smooth Serpentine Path ---")
    y_step_um = float(input("Enter the desired distance between horizontal scan lines (um): "))
    y_step = y_step_um * stage.steps_per_micron
    
    # This function guarantees a smooth hardware sweep by ONLY passing the edge coordinates
    scan_points = generate_rectangle_serpentine_path_smooth(polygon.bounds, y_step=y_step)
    
    print(f"Generated {len(scan_points)} scan points.")
    
    # ---------------------------------------------------------
    # 3. SPEED CONTROL (Velocity mapping)
    # ---------------------------------------------------------
    print("\n--- Speed Control ---")
    sweep_time_str = input("Enter the time (in seconds) it should take to sweep one horizontal line: ")
    try:
        sweep_time = float(sweep_time_str)
        if sweep_time <= 0:
            raise ValueError("Sweep time must be greater than 0.")
        
        # Calculate physical width in microns using the polygon bounds
        min_x, _, max_x, _ = polygon.bounds
        width_steps = max_x - min_x
        width_um = width_steps / stage.steps_per_micron
        
        # Calculate required velocity (microns / second)
        velocity_um_s = width_um / sweep_time
        print(f"Calculated line width: {width_um:.2f} um")
        print(f"Setting stage velocity to {velocity_um_s:.2f} um/s to achieve a {sweep_time}s sweep.")
        
        # Command the hardware
        stage.set_velocity(velocity_um_s)
        
    except ValueError as e:
        print(f"Invalid time: {e}")
        return
    
    # ---------------------------------------------------------
    # 4. VISUALIZATION & HARDWARE EXECUTION
    # ---------------------------------------------------------
    vertices_mm = vertices / (1000 * stage.steps_per_micron)
    scan_points_mm = scan_points / (1000 * stage.steps_per_micron)

    # Visualize the defined polygon
    fig, ax = plt.subplots()
    ax.plot(vertices_mm[:, 0], vertices_mm[:, 1], 'ro-')
    ax.set_title("Defined Polygon")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    ax.fill(vertices_mm[:, 0], vertices_mm[:, 1], alpha=0.3)
    if len(scan_points_mm) > 0:
        ax.plot(scan_points_mm[:, 0], scan_points_mm[:, 1], 'b.-', lw=0.8, ms=2)
        ax.scatter(scan_points_mm[0, 0], scan_points_mm[0, 1], c='g', s=40, label='Start')
        ax.scatter(scan_points_mm[-1, 0], scan_points_mm[-1, 1], c='k', s=40, label='End')
        ax.legend()
        
    # --- NEW IMAGE SAVING BLOCK ---
    save_img_choice = input("Save an image of the ROI plot to 'roi_image.png'? (y/n): ")
    if save_img_choice.lower() == 'y':
        # dpi=300 makes it high resolution, bbox_inches='tight' removes excess white borders
        plt.savefig("roi_image.png", dpi=300, bbox_inches='tight')
        print("ROI image saved to 'roi_image.png'.")
    else:
        print("ROI image not saved.")
    # ------------------------------

    plt.show()
    plt.close(fig)

    save_choice = input("Save scan points to 'scan_points.csv'? (y/n): ")
    if save_choice.lower() == 'y':
        np.savetxt("scan_points.csv", scan_points, delimiter=",", header="x_steps,y_steps", comments="")
        print("Scan points saved to 'scan_points.csv'.")
    else:
        print("Scan points not saved.")

    # Define interval on each scan point
    interval = input("Enter the interval (ms) to stay at the edges of each scan line: ")
    try:
        interval_ms = float(interval)
        if interval_ms < 0:
            raise ValueError("Interval must be non-negative.")
    except ValueError as e:
        print(f"Invalid interval: {e}")
        return

    # Begin scan execution
    input("Press Enter to start the scan...")
    try:
        stage.move_to(*scan_points[0])
        shutter.open()
        stage.scan(scan_points, interval_ms)  
    finally:
        shutter.close()
        print("Shutter safely closed.")
        
    print("Scan completed.")
    print('Serpentine scan finished. You may now safely exit the program.')
    print("=" * 40)
    

if __name__ == "__main__":
    main()