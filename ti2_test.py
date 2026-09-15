"""联合测试：相机采流 + Ti2 显微镜对比度自动对焦"""
from laserlab.camera import NikonDSFi3Camera
from laserlab.ti2 import NikonTi2

CAMERA_DLL = r"C:\Program Files\Nikon\DSCamSDK\Samples\KsCamExample\SDK\DSCam.dll"

def test_autofocus_with_camera():
    with NikonTi2() as mic, NikonDSFi3Camera(
        dll_path=CAMERA_DLL,
        camera_index=0,
        exposure_s=0.006,
        verbose=False,
    ) as cam:

        print("执行自动对焦...")
        mic.set_dia_lamp(on=True, percent=100)  # 打开透射光
        coarse_result, fine_result = mic.quick_autofocus_with_camera(
            cam,
            speed=1,
            coarse_half_range_um=100,
            coarse_steps=10,
            fine_half_range_um=20,
            fine_steps=30,
        )
        print(
            f"粗调最佳 Z: {coarse_result.best_z_um:.2f} um, "
            f"清晰度: {coarse_result.best_score:.2f}\n"
            f"精调最佳 Z: {fine_result.best_z_um:.2f} um, "
            f"清晰度: {fine_result.best_score:.2f}, "
            f"当前位置: {mic.get_z():.2f} um"
        )

if __name__ == "__main__":
    # Print current z position
    with NikonTi2() as mic:
        z_pos = mic.get_z()
        print(f"当前 Z 位置: {z_pos:.2f} um")
    test_autofocus_with_camera()