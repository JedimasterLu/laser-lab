# This is a pipeline that allows us to see CB particles and categorize them into CB with bubbles and CB without bubbles. 
# The following is a test using a single image. Can be extended to a video stream or a folder of images.

import cv2
import numpy as np
import matplotlib.pyplot as plt

# --- 1. Load Image & Pre-process ---
img_path = r"C:\Users\rishi\Desktop\SURF\CODING\Image Processing\Image Detection\Test1.jpg" 
frame = cv2.imread(img_path)
frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

img_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
blur = cv2.GaussianBlur(img_gray, (13, 13), 0)

# --- 2. Total Carbon Black Detection ---
ret, mask = cv2.threshold(blur, 140, 255, cv2.THRESH_BINARY_INV)
mask_clean = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3,3), np.uint8))

# ==========================================
# --- NEW: THE PARTICLE FILTER (Area > 50) ---
# ==========================================
raw_cb_contours, _ = cv2.findContours(mask_clean, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Create a blank canvas to hold ONLY the valid carbon black particles
filtered_cb_mask = np.zeros_like(mask_clean)

# Draw only the particles larger than 50 pixels
for cnt in raw_cb_contours:
    if cv2.contourArea(cnt) > 50:
        cv2.drawContours(filtered_cb_mask, [cnt], -1, 255, -1)

# --- 3. Bubble Detection (Canny Subtraction) ---
edges = cv2.Canny(mask, 5, 15)
edges_normal = cv2.Canny(blur, 5, 15)

difference = cv2.absdiff(edges, edges_normal)
closed_diff = cv2.morphologyEx(difference, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
diff_contours, _ = cv2.findContours(closed_diff, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Draw the solid bubble zones
bubble_zone_mask = np.zeros_like(mask)
for cnt in diff_contours:
    if cv2.contourArea(cnt) > 690:  # Your tuned bubble area threshold
        cv2.drawContours(bubble_zone_mask, [cnt], -1, 255, -1)

# ==========================================
# --- 4. THE CATEGORIZATION ---
# ==========================================

# Category A: CB WITH Bubbles (Intersection)
# Notice we are now using 'filtered_cb_mask' instead of 'mask_clean'
cb_with_bubbles = cv2.bitwise_and(filtered_cb_mask, bubble_zone_mask)

# Category B: CB WITHOUT Bubbles (Total Valid CB minus Bubbled CB)
cb_without_bubbles = cv2.bitwise_xor(filtered_cb_mask, cb_with_bubbles)

# ==========================================
# --- 5. Extract Contours & Visualize ---
# ==========================================

contours_with, _ = cv2.findContours(cb_with_bubbles, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
contours_without, _ = cv2.findContours(cb_without_bubbles, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

# Create blank canvases to draw our results on
canvas_with = np.zeros_like(frame_rgb)
canvas_without = np.zeros_like(frame_rgb)
master_overlay = frame_rgb.copy()

# Draw "With Bubbles" as Green
cv2.drawContours(canvas_with, contours_with, -1, (0, 255, 0), 2)
cv2.drawContours(master_overlay, contours_with, -1, (0, 255, 0), 2)

# Draw "Without Bubbles" as Red
cv2.drawContours(canvas_without, contours_without, -1, (255, 0, 0), 2)
cv2.drawContours(master_overlay, contours_without, -1, (255, 0, 0), 2)

# Display the Final Dashboards
print(f"Active Particles (With Bubbles): {len(contours_with)}")
print(f"Dormant Particles (No Bubbles): {len(contours_without)}")

'''plt.figure(figsize=(18, 6))

plt.subplot(1, 4, 1)
plt.imshow(img_gray, cmap='gray')
plt.title("Original Grayscale Image")
plt.axis('off')

plt.subplot(1,4, 2)
plt.imshow(canvas_with)
plt.title(f"CB WITH Bubbles ({len(contours_with)} found)")
plt.axis('off')

plt.subplot(1, 4, 3)
plt.imshow(canvas_without)
plt.title(f"CB WITHOUT Bubbles ({len(contours_without)} found)")
plt.axis('off')

plt.subplot(1, 4, 4)
plt.imshow(master_overlay)
plt.title("Master Overlay (Green = Active, Red = Dormant)")
plt.axis('off')

plt.tight_layout()
#plt.show()

'''
plt.figure(figsize=(20, 12))
plt.subplot(1,2,1)
plt.imshow(img_gray, cmap='gray')
plt.axis('off')

plt.subplot(1,2,2)
plt.imshow(master_overlay)
plt.axis('off')

plt.show()