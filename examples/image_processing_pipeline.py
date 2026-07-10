import cv2
import numpy as np

def process_bubble_frame(frame, cb_area_min=50, bubble_area_min=690):
    """
    Categorizes CB particles and calculates positions/radii.
    Returns: active_data, dormant_data, annotated_frame
    """
    # 1. Pre-process
    img_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(img_gray, (9, 9), 0)

    # 2. Total Carbon Black Detection & Area Filter
    ret, mask = cv2.threshold(blur, 140, 255, cv2.THRESH_BINARY_INV)
    mask_clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))
    
    raw_cb_contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filtered_cb_mask = np.zeros_like(mask_clean)
    for cnt in raw_cb_contours:
        if cv2.contourArea(cnt) > cb_area_min:
            cv2.drawContours(filtered_cb_mask, [cnt], -1, 255, -1)

    # 3. Bubble Detection (Canny Subtraction)
    edges = cv2.Canny(mask, 5, 15)
    edges_normal = cv2.Canny(blur, 5, 15)
    difference = cv2.absdiff(edges, edges_normal)
    closed_diff = cv2.morphologyEx(difference, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    diff_contours, _ = cv2.findContours(closed_diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    bubble_zone_mask = np.zeros_like(mask)
    for cnt in diff_contours:
        if cv2.contourArea(cnt) > bubble_area_min:
            cv2.drawContours(bubble_zone_mask, [cnt], -1, 255, -1)

    # 4. Categorization
    cb_with_bubbles = cv2.bitwise_and(filtered_cb_mask, bubble_zone_mask)
    cb_without_bubbles = cv2.bitwise_xor(filtered_cb_mask, cb_with_bubbles)

    # 5. Extract Coords & Annotate
    active_data = []
    dormant_data = []
    annotated = frame.copy()

    # Get "With Bubbles" (Green)
    contours_with, _ = cv2.findContours(cb_with_bubbles, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours_with:
        (x, y), radius = cv2.minEnclosingCircle(cnt)
        active_data.append({'x': x, 'y': y, 'r': radius})
        cv2.circle(annotated, (int(x), int(y)), int(radius), (0, 255, 0), 2)

    # Get "Without Bubbles" (Red)
    contours_without, _ = cv2.findContours(cb_without_bubbles, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours_without:
        (x, y), radius = cv2.minEnclosingCircle(cnt)
        dormant_data.append({'x': x, 'y': y, 'r': radius})
        cv2.circle(annotated, (int(x), int(y)), int(radius), (0, 0, 255), 2)

    return active_data, dormant_data, annotated