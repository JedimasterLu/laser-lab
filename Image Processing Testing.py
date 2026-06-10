import numpy as np
import cv2

def nothing(x):
    # Callback function required by trackbars, does nothing
    pass

# Initialize webcam (0 is usually the built-in laptop camera)
cap = cv2.VideoCapture(0)

# Create the main output window
cv2.namedWindow('Live CV Pipeline')

# Create trackbars for real-time tuning
cv2.createTrackbar('Blur Size', 'Live CV Pipeline', 5, 21, nothing)
cv2.createTrackbar('Threshold', 'Live CV Pipeline', 80, 255, nothing)
cv2.createTrackbar('Min Area', 'Live CV Pipeline', 500, 5000, nothing)

print("Starting live feed. Press 'q' to quit.")

while True:
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame. Is another app using your camera?")
        break

    # 1. Get current positions of trackbars
    blur_val = cv2.getTrackbarPos('Blur Size', 'Live CV Pipeline')
    thresh_val = cv2.getTrackbarPos('Threshold', 'Live CV Pipeline')
    min_area = cv2.getTrackbarPos('Min Area', 'Live CV Pipeline')

    # Ensure blur is an odd number and at least 1 (OpenCV requirement)
    blur_val = max(1, blur_val)
    if blur_val % 2 == 0:
        blur_val += 1

    # 2. Grayscale Conversion
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # 3. Blurring
    blurred = cv2.GaussianBlur(gray, (blur_val, blur_val), 0)

    # 4. Thresholding (Inverse binary: dark objects become solid white)
    _, thresh = cv2.threshold(blurred, thresh_val, 255, cv2.THRESH_BINARY_INV)

    # 5. Find Contours
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # 6. Filter and Draw
    output = frame.copy()
    valid_count = 0
    
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area > min_area:
            valid_count += 1
            
            # Draw the contour boundary in bright green
            cv2.drawContours(output, [cnt], -1, (0, 255, 0), 2)
            
            # Calculate the centroid (center of mass)
            M = cv2.moments(cnt)
            if M["m00"] != 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])
                # Draw a red dot exactly at the center coordinate
                cv2.circle(output, (cx, cy), 5, (0, 0, 255), -1)

    # Overlay particle count text
    cv2.putText(output, f"Dark Objects Found: {valid_count}", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 0, 0), 2)

    # Show the final drawn image
    cv2.imshow('Live CV Pipeline', output)
    
    # Show the raw threshold mask (what the computer ACTUALLY uses to find shapes)
    cv2.imshow('The Computer Brain (Mask)', thresh)

    # Break loop if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Clean up hardware connections
cap.release()
cv2.destroyAllWindows()