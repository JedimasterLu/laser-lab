import numpy as np
import matplotlib.pyplot as plt
import laserlab
from shapely.geometry import GeometryCollection, LineString, MultiLineString, Point, Polygon
from laserlab import stage

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

def find_self_intersections(vertices: np.ndarray) -> list[tuple[float, float]]:
    """Return all non-adjacent edge intersection points of a polygon."""
    n = len(vertices)
    intersections: list[tuple[float, float]] = []
    if n < 4:
        return intersections

    edges = [
        (vertices[i], vertices[(i + 1) % n])
        for i in range(n)
    ]

    for i, (a1, a2) in enumerate(edges):
        line_a = LineString([a1, a2])
        for j in range(i + 1, n):
            # Skip adjacent edges and the first-last pair.
            if j == i or j == (i + 1) % n or i == (j + 1) % n:
                continue

            b1, b2 = edges[j]
            line_b = LineString([b1, b2])
            inter = line_a.intersection(line_b)
            if inter.is_empty:
                continue

            if isinstance(inter, Point):
                intersections.append((inter.x, inter.y))
            else:
                # Collinear overlap or multi-point intersection also means invalid polygon.
                rep = inter.representative_point()
                intersections.append((rep.x, rep.y))

    # Deduplicate numerical duplicates.
    unique = []
    for x, y in intersections:
        if not any(abs(x - ux) < 1e-6 and abs(y - uy) < 1e-6 for ux, uy in unique):
            unique.append((x, y))
    return unique

def generate_serpentine_path(
    polygon: Polygon,
    y_step: float,
    x_step: float | None = None,
) -> np.ndarray:
    """Generate serpentine scan points inside polygon in stage-step coordinates."""
    min_x, min_y, max_x, max_y = polygon.bounds
    y_values = np.arange(min_y, max_y + y_step, y_step)

    path: list[tuple[float, float]] = []
    left_to_right = True

    for y in y_values:
        scan_line = LineString([(min_x - 1.0, y), (max_x + 1.0, y)])
        inter = polygon.intersection(scan_line)
        if inter.is_empty:
            continue

        segments = []
        if isinstance(inter, LineString):
            segments = [inter]
        elif isinstance(inter, MultiLineString):
            segments = list(inter.geoms)
        elif isinstance(inter, Point):
            segments = [LineString([(inter.x, y), (inter.x, y)])]
        elif isinstance(inter, GeometryCollection):
            segments = [g for g in inter.geoms if isinstance(g, LineString)]

        intervals = []
        for seg in segments:
            coords = np.array(seg.coords)
            x0 = float(np.min(coords[:, 0]))
            x1 = float(np.max(coords[:, 0]))
            intervals.append((x0, x1))

        intervals.sort(key=lambda item: item[0])
        if not left_to_right:
            intervals.reverse()

        for x0, x1 in intervals:
            if x_step is None or x_step <= 0:
                x_samples = np.array([x0, x1])
            else:
                if left_to_right:
                    x_samples = np.arange(x0, x1 + x_step, x_step)
                else:
                    x_samples = np.arange(x1, x0 - x_step, -x_step)

            for x in x_samples:
                path.append((float(x), float(y)))

        left_to_right = not left_to_right

    return np.array(path)

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
    print("Select the type of region to pattern:")
    print(" 1: Rectangle defined by two diagonal corners")
    print(" 2: Freeform polygon defined by vertices")
    
    choice_shape = ""
    while choice_shape not in ["1", "2"]: 
        choice_shape = input("Enter your choice (1 or 2): ")
        if choice_shape not in ["1", "2"]:
            print("Invalid choice. Please enter '1' or '2'.")
    
    if choice_shape == "1":
        print("\n--- Rectangle Mode ---")
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
            print("Rectangle generated successfully.")
        except ValueError as e:
            print(f"Error: {e}")
            return # Safely exit if the area is zero
            
    elif choice_shape == "2":
        print("\n--- Custom Polygon Mode ---")
        print("Enter 'a' to add a vertex, 'q' to finish.")
        print("Please use the joystick to move to the desired position before pressing 'a'.")
        
        # Collect vertices from user input
        vertices = []
        new_input = ""
        while new_input != "q":
            new_input = input("Enter command: ")
            if new_input == "a":
                vertices.append(stage.position)
                print(f"Vertex added: {stage.position}, total vertices: {len(vertices)}")
            elif new_input == "q":
                print("Finished defining polygon.")
            else:
                print("Invalid command. Please enter 'a' or 'q'.")
        vertices = np.array(vertices)
        if len(vertices) < 3:
            raise ValueError("At least 3 vertices are required to define a polygon.")

        # Validate polygon has no edge intersections and encloses a single region.
        intersections = find_self_intersections(vertices)
        if intersections:
            print("Detected invalid polygon (self-intersections found):")
            for i, (x, y) in enumerate(intersections, start=1):
                print(f"  {i}. intersection near stage steps ({x:.2f}, {y:.2f})")
            raise ValueError("Polygon edges intersect. Please redefine a simple polygon.")

    polygon = Polygon(vertices)
    if (not polygon.is_valid) or polygon.area <= 0:
        raise ValueError("Invalid polygon. Please ensure vertices define one closed area.")
    
    # Path generation logic based on shape selection
    if choice_shape == "1":
        print("\nSelect the serpentine path generation method:")
        print(" 1: Fast rectangle method (smooth endpoints only)")
        print(" 2: General polygon method (works for any shape)")
        
        choice_path = ""
        while choice_path not in ["1", "2"]: 
            choice_path = input("Enter your choice (1 or 2): ")
            if choice_path not in ["1", "2"]:
                print("Invalid choice. Please enter '1' or '2'.")
                
        if choice_path == "1":
            y_step_um = float(input("Enter the desired Y step size (um): "))
            y_step = y_step_um * stage.steps_per_micron
            scan_points = generate_rectangle_serpentine_path_smooth(polygon.bounds, y_step=y_step)
        else:
            # Fallback to general method for rectangle if they chose '2'
            print("Enter 0 for the x_step_um to make smooth path.")
            x_step_um = float(input("Enter the desired X step size (um): "))
            y_step_um = float(input("Enter the desired Y step size (um): "))
            x_step = x_step_um * stage.steps_per_micron
            y_step = y_step_um * stage.steps_per_micron
            scan_points = generate_serpentine_path(polygon, y_step=y_step, x_step=x_step)
            
    else:
        # Freeform polygons MUST use the general shapely method
        print("\nUsing general polygon path generation for custom shape.")
        print("Enter 0 for the x_step_um to make smooth path.")
        x_step_um = float(input("Enter the desired X step size (um): "))
        y_step_um = float(input("Enter the desired Y step size (um): "))
        x_step = x_step_um * stage.steps_per_micron
        y_step = y_step_um * stage.steps_per_micron
        scan_points = generate_serpentine_path(polygon, y_step=y_step, x_step=x_step)
    
    print(f"Generated {len(scan_points)} scan points.")

    vertices_mm = vertices / (1000 * stage.steps_per_micron)
    scan_points_mm = scan_points / (1000 * stage.steps_per_micron)

    # Visualize the defined polygon
    fig, ax = plt.subplots()
    ax.plot(vertices_mm[:, 0], vertices_mm[:, 1], 'ro-')
    ax.set_title("Defined Polygon")
    ax.set_xlabel("X (mm)")
    ax.set_ylabel("Y (mm)")
    # Fill the polygon for better visualization
    ax.fill(vertices_mm[:, 0], vertices_mm[:, 1], alpha=0.3)
    if len(scan_points_mm) > 0:
        ax.plot(scan_points_mm[:, 0], scan_points_mm[:, 1], 'b.-', lw=0.8, ms=2)
        ax.scatter(scan_points_mm[0, 0], scan_points_mm[0, 1], c='g', s=40, label='Start')
        ax.scatter(scan_points_mm[-1, 0], scan_points_mm[-1, 1], c='k', s=40, label='End')
        ax.legend()
    plt.show()
    plt.close(fig)

    save_choice = input("Save scan points to 'scan_points.csv'? (y/n): ")
    if save_choice.lower() == 'y':
        np.savetxt("scan_points.csv", scan_points, delimiter=",", header="x_steps,y_steps", comments="")
        print("Scan points saved to 'scan_points.csv'.")
    else:
        print("Scan points not saved.")

    # Define interval on each scan point
    interval = input("Enter the interval (ms) to stay at each scan point: ")
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
        stage.scan(scan_points, interval_ms)  # Adjust speed as needed
    finally:
        shutter.close()
        print("Shutter safely closed.")
        
    print("Scan completed.")

    print('Serpentine scan finished. You may now safely exit the program.')
    print("=" * 40)
    

if __name__ == "__main__":
    main()
    