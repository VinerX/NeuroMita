import cv2
import time
import numpy as np
import cv2
from CameraCapture import CameraCapture

def get_camera_list():
    """
    Checks for available cameras and returns a list of their indices.
    """
    camera_list = []
    for i in range(10):  # Check up to 10 cameras
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            camera_list.append(i)
            cap.release()
    return camera_list

def main():
    available_cameras = get_camera_list()
    if not available_cameras:
        print("No cameras found.")
        return

    print("Available cameras:", available_cameras,len(available_cameras))

    camera_index = available_cameras[0]  # Use the first available camera
    camera_capture = CameraCapture()
    camera_capture.start_capture(camera_index=camera_index, quality=50, fps=1, capture_width=640, capture_height=480)

    try:
        start_time = time.time()
        frame_count = 0
        while True:
            frame = camera_capture.get_latest_frame()
            if frame is not None:
                print("Frame available")
                img = cv2.imdecode(np.frombuffer(frame, np.uint8), cv2.IMREAD_COLOR)

                cv2.imshow('Camera Capture', img)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('s'):
                    filename = f"capture_{frame_count:04d}.png"
                    cv2.imwrite(filename, img)
                    print(f"Saved {filename}")
                    frame_count += 1
                elif key == ord('q'):
                    break
            else:
                print("No frame available")
                time.sleep(0.1)

    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        camera_capture.stop_capture()
        cv2.destroyAllWindows()


main()