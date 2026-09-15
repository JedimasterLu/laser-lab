from laserlab.ti2 import NikonTi2

with NikonTi2() as mic:                    # 无设备时加 simulator=True
    mic.set_z(100.0)                       # Z, um
    z = mic.get_z()

    mic.set_dia_lamp(on=True, percent=50)  # 透射灯 0–100%
    mic.set_epi_led(1, on=True, level=4)   # EPI 通道 1–4，档位 1–6 = 10–100%

    mic.set_turret(1, position=3, shutter=True)  # turret 1|2，位 1–6
    mic.set_filter(1, 2)                         # 滤光轮 1|2，位 1–7

    # 荧光/对比度自动对焦（Auto Focus FLUO，基于 RUN_AF / AF-ZPRINT）
    ok = mic.autofocus(io_channel=1, scan_duration_s=1.0)
