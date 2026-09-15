"""联合测试：相机采流 + Ti2 显微镜对比度自动对焦"""
import time
import cv2
import numpy as np
from laserlab.camera import NikonDSFi3Camera
from laserlab.ti2 import NikonTi2

CAMERA_DLL = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"

def calculate_sharpness(image: np.ndarray) -> float:
    """使用拉普拉斯算子方差评估图像清晰度"""
    if image.dtype == np.uint16:
        img_8u = (image >> 4).astype(np.uint8)
    else:
        img_8u = image.astype(np.uint8)
    return float(cv2.Laplacian(img_8u, cv2.CV_64F).var())

def test_autofocus_with_camera():
    with NikonTi2() as mic, NikonDSFi3Camera(
        dll_path=CAMERA_DLL,
        camera_index=0,
        exposure_s=0.003,
        verbose=False,
    ) as cam:
        mic.set_dia_lamp(on=True, percent=100)  # 打开透射光

        sharpness_list: list[float] = []

        def capture_during_af():
            """在显微镜 Z 轴扫描期间执行的相机采集回调"""
            print("正在随 Z 轴移动连续采集帧并计算清晰度...")
            # 持续采集若干帧（对应 Ti2 扫描区间）
            for frame_idx in range(1, 40):
                img = cam.get_image()
                score = calculate_sharpness(img)
                sharpness_list.append(score)
                print(f"Frame #{frame_idx:02d} | Sharpness: {score:.2f}")
                time.sleep(0.01)

        # 执行自动对焦
        # 如果硬件已连接 TTL 信号线，显微镜会记录切片索引；
        # 若未连 TTL 线，可设 move_to_best=False 避免触发硬件索引越界。
        ok = mic.autofocus(
            io_channel=1,
            z_relative_dev=300000,    # 搜索范围
            speed=9,
            live_callback=capture_during_af,
            move_to_best=False,       # 纯软件分析最佳帧
        )

        if sharpness_list:
            best_idx = int(np.argmax(sharpness_list)) + 1
            max_score = sharpness_list[best_idx - 1]
            print(f"\n自动对焦完成! 最佳对焦帧序号: #{best_idx} (清晰度得分: {max_score:.2f})")

if __name__ == "__main__":
    # Print current z position
    import sys
    with NikonTi2() as mic:
        z_pos = mic.get_z()
        print(f"当前 Z 位置: {z_pos:.2f} um")
    # test_autofocus_with_camera()