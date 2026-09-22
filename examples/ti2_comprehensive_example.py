"""
Comprehensive examples of all major functions in laserlab.ti2.NikonTi2

This script demonstrates the usage of every major function in the Nikon Ti2 microscope
control library. Requires actual hardware connection.
"""

from laserlab.ti2 import NikonTi2


# =============================================================================
# SECTION 1: Initialization and Basic Connection
# =============================================================================

def example_initialization():
    """Example 1: Initialize Ti2 connection"""
    print("=" * 70)
    print("EXAMPLE 1: Initialization")
    print("=" * 70)

    # Option A: Use default DLL location
    ti2 = NikonTi2()
    print(f"Connected to Ti2: {ti2}")
    print(f"Z limits: {ti2.z_min_um:.1f} - {ti2.z_max_um:.1f} µm")
    ti2.close()

    # Option B: Use custom DLL path
    # ti2 = NikonTi2(dll_path="C:\\Path\\To\\Ti2_Mic_Driver.dll")

    # Option C: Use custom Z limits
    # ti2 = NikonTi2(z_min_um=400.0, z_max_um=2700.0)

    print()


def example_context_manager():
    """Example 2: Using NikonTi2 as a context manager for automatic cleanup"""
    print("=" * 70)
    print("EXAMPLE 2: Context Manager (Automatic Cleanup)")
    print("=" * 70)

    # Recommended approach: use 'with' statement for automatic cleanup
    with NikonTi2() as ti2:
        print(f"Connected to Ti2: {ti2}")
        # All operations here
        current_z = ti2.get_z()
        print(f"Current Z position: {current_z:.2f} µm")
    # Automatically closed when exiting the 'with' block

    print()


# =============================================================================
# SECTION 2: Stage Positioning (Z, X, Y)
# =============================================================================

def example_stage_positioning():
    """Example 3: Stage positioning in Z, X, and Y dimensions"""
    print("=" * 70)
    print("EXAMPLE 3: Stage Positioning (Z, X, Y)")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Check hardware capabilities
        print(f"Accessory mask: {hex(ti2.accessory_mask)}")
        has_xy = bool(ti2.accessory_mask & 0x6)  # Check for X (0x2) and Y (0x4)
        print(f"XY Stage available: {has_xy}\n")

        # Get current positions
        current_z = ti2.get_z()
        current_x = ti2.get_x()
        current_y = ti2.get_y()
        print(f"Current position: Z={current_z:.2f} µm, X={current_x:.2f} µm, Y={current_y:.2f} µm")

        # Get metadata to check stage ranges
        try:
            metadata = ti2.get_metadata()
            # Check physical ranges from metadata
            for i, (name, ranges) in enumerate([
                ("X range", metadata.iXYStage_XRangePhys),
                ("Y range", metadata.iXYStage_YRangePhys),
            ]):
                print(f"  {name}: {ranges}")
        except Exception as e:
            print(f"  Could not read metadata: {e}")

        # Set Z position
        new_z = 1000.0  # in micrometers
        actual_z = ti2.set_z(new_z, speed=5, tolerance=0)
        print(f"\nSet Z to {new_z:.2f} µm (actual: {actual_z:.2f} µm)")

        # Set X position
        new_x = 100.0
        actual_x = ti2.set_x(new_x, speed=3, tolerance=0)
        print(f"Set X to {new_x:.2f} µm (actual: {actual_x:.2f} µm)")
        if actual_x == current_x:
            print("  ⚠ X position unchanged after set command")
            if not has_xy:
                print("    → XY stage not detected in accessory_mask")
            else:
                print("    → XY stage detected but not responding:")
                print("      • Check if XY stage is powered and connected")
                print("      • Check if stage is at physical limit and locked")
                print("      • Check SDK compatibility with your stage model")

        # Set Y position
        new_y = 200.0
        actual_y = ti2.set_y(new_y, speed=3, tolerance=0)
        print(f"Set Y to {new_y:.2f} µm (actual: {actual_y:.2f} µm)")
        if actual_y == current_y:
            print("  ⚠ Y position unchanged after set command")

    print()


# =============================================================================
# SECTION 3: Optical Component Control
# =============================================================================

def example_nosepiece_control():
    """Example 4: Nosepiece (objective turret) control"""
    print("=" * 70)
    print("EXAMPLE 4: Nosepiece Control")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Get current nosepiece position
        current_pos = ti2.get_nosepiece()
        print(f"Current nosepiece position: {current_pos} (1-6)")

        # Switch to different objectives
        for position in [1, 2, 3]:
            actual_pos = ti2.set_nosepiece(position)
            print(f"Set nosepiece to position {position} (actual: {actual_pos})")

    print()


def example_condenser_control():
    """Example 5: Condenser (illumination) control"""
    print("=" * 70)
    print("EXAMPLE 5: Condenser Control")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Get current condenser position
        current_pos = ti2.get_condenser()
        print(f"Current condenser position: {current_pos} (1-7)")

        # Set different condenser positions (e.g., BF, DF, PH)
        for position in [1, 3, 5]:
            actual_pos = ti2.set_condenser(position)
            print(f"Set condenser to position {position} (actual: {actual_pos})")

    print()


def example_lightpath_control():
    """Example 6: Light path control (eyepiece, camera port, etc.)"""
    print("=" * 70)
    print("EXAMPLE 6: Light Path Control")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Get current light path
        current_path = ti2.get_lightpath()
        print(f"Current light path position: {current_path} (1-4)")

        # Switch between light paths
        for path in [1, 2, 4]:
            actual_path = ti2.set_lightpath(path)
            print(f"Set light path to {path} (actual: {actual_path})")

    print()


def example_turret_control():
    """Example 7: Turret and turret shutter control"""
    print("=" * 70)
    print("EXAMPLE 7: Turret Control (Revolving Nosepiece/Analyzer)")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Control Turret 1 (e.g., filter turret)
        current_pos = ti2.get_turret(turret=1)
        print(f"Turret 1 current position: {current_pos} (1-6)")

        # Set turret 1 position and open/close shutter
        actual_pos = ti2.set_turret(turret=1, position=2, shutter=True)
        print(f"Turret 1 position: {actual_pos}, shutter open")

        # Control Turret 2
        current_pos = ti2.get_turret(turret=2)
        print(f"Turret 2 current position: {current_pos} (1-6)")

        # Set turret 2 with different parameters
        actual_pos = ti2.set_turret(turret=2, position=3, shutter=False)
        print(f"Turret 2 position: {actual_pos}, shutter closed")

    print()


def example_filter_control():
    """Example 8: Filter wheel control"""
    print("=" * 70)
    print("EXAMPLE 8: Filter Wheel Control")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Filter wheel 1 (barrier filters)
        current_filter1 = ti2.get_filter(wheel=1)
        print(f"Filter wheel 1 current position: {current_filter1} (1-7)")

        # Switch filter wheel 1
        actual_filter1 = ti2.set_filter(wheel=1, position=2)
        print(f"Filter wheel 1 set to position 2 (actual: {actual_filter1})")

        # Filter wheel 2 (dichroic filters)
        current_filter2 = ti2.get_filter(wheel=2)
        print(f"Filter wheel 2 current position: {current_filter2} (1-7)")

        # Switch filter wheel 2
        actual_filter2 = ti2.set_filter(wheel=2, position=4)
        print(f"Filter wheel 2 set to position 4 (actual: {actual_filter2})")

    print()


# =============================================================================
# SECTION 4: Illumination Control
# =============================================================================

def example_shutter_control():
    """Example 9: Shutter control (EPI, DIA, AUX)"""
    print("=" * 70)
    print("EXAMPLE 9: Shutter Control")
    print("=" * 70)

    with NikonTi2() as ti2:
        shutters = ["epi", "dia", "aux"]

        for shutter_name in shutters:
            # Get current shutter state
            is_open = ti2.get_shutter(shutter_name)
            print(f"{shutter_name.upper()} shutter is {'open' if is_open else 'closed'}")

            # Open shutter
            actual_state = ti2.set_shutter(shutter_name, on=True)
            print(f"  Opened {shutter_name} shutter (actual: {actual_state})")

            # Close shutter
            actual_state = ti2.set_shutter(shutter_name, on=False)
            print(f"  Closed {shutter_name} shutter (actual: {actual_state})")

    print()


def example_dia_lamp_control():
    """Example 10: DIA lamp (transmitted light) control"""
    print("=" * 70)
    print("EXAMPLE 10: DIA Lamp Control (Transmitted Light)")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Get current DIA lamp state
        is_on, brightness = ti2.get_dia_lamp()
        print(f"DIA lamp: {'ON' if is_on else 'OFF'}, brightness: {brightness:.1f}%")

        # Turn on and set brightness to 50%
        is_on, brightness = ti2.set_dia_lamp(on=True, percent=50.0)
        print(f"Set DIA lamp to ON at 50% (actual: {is_on}, {brightness:.1f}%)")

        # Set to 100%
        is_on, brightness = ti2.set_dia_lamp(percent=100.0)
        print(f"Set DIA lamp to 100% (actual: {brightness:.1f}%)")

        # Turn off
        is_on, brightness = ti2.set_dia_lamp(on=False)
        print(f"Turned OFF DIA lamp (actual: {is_on})")

    print()


def example_epi_led_control():
    """Example 11: EPI LED control (fluorescence illumination)"""
    print("=" * 70)
    print("EXAMPLE 11: EPI LED Control (Fluorescence)")
    print("=" * 70)

    with NikonTi2() as ti2:
        # EPI has 4 channels (1-4), each with levels 1-6 (10-100%)
        for channel in [1, 2]:
            # Get current state
            is_on, level = ti2.get_epi_led(channel)
            print(f"EPI LED channel {channel}: {'ON' if is_on else 'OFF'}, level: {level}/6")

            # Turn on at level 3 (50%)
            is_on, level = ti2.set_epi_led(channel, on=True, level=3)
            print(f"  Set to ON, level 3 (actual: {is_on}, level {level})")

            # Increase to level 5 (80%)
            is_on, level = ti2.set_epi_led(channel, level=5)
            print(f"  Set to level 5 (actual: level {level})")

            # Turn off
            is_on, level = ti2.set_epi_led(channel, on=False)
            print(f"  Turned OFF (actual: {is_on})")

    print()


# =============================================================================
# SECTION 5: Perfect Focus System (PFS)
# =============================================================================

def example_pfs_control():
    """Example 12: Perfect Focus System (PFS) control"""
    print("=" * 70)
    print("EXAMPLE 12: Perfect Focus System (PFS)")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Turn on PFS (autofocus maintenance)
        ti2.pfs_on()
        print("Turned on Perfect Focus System")

        # Check PFS status
        status = ti2.pfs_status()
        print(f"PFS status: {status}")

        # Search for focus offset
        ti2.pfs_search_offset(stop_level=0)
        print("Initiated PFS search offset")

        # Wait for PFS to settle (blocks until complete or timeout)
        offset, final_status = ti2.pfs_wait(timeout_ms=10000)
        print(f"PFS settled: offset={offset}, status={final_status}")

        # Turn off PFS
        ti2.pfs_off()
        print("Turned off Perfect Focus System")

    print()


# =============================================================================
# SECTION 6: Autofocus Operations
# =============================================================================

def example_af_sdk_mode():
    """Example 13: SDK-based autofocus (contrast AF / Auto Focus FLUO)"""
    print("=" * 70)
    print("EXAMPLE 13: SDK-Based Autofocus (Contrast AF)")
    print("=" * 70)

    with NikonTi2() as ti2:
        print("Note: This example shows the workflow; actual hardware may differ")

        # Step 1: Configure I/O ports for autofocus
        ti2.af_setup_io(io_mask=0x00, falling_edge_mask=0x100)
        print("Configured I/O control box for AF")

        # Step 2: Move to scan start position
        ti2.set_z(1200.0, speed=1)
        print("Moved to scan start position")

        # Step 3: Start AF scan
        # (In real use, this would be triggered by camera exposure signals)
        ti2.af_start(io_channel=1, z_relative_dev=500000, speed=9)
        print("Started AF scan (acquisition would happen here)")

        # Step 4: Retrieve AF data
        # In real hardware, wait for exposures here
        z_positions = ti2.af_get_z_positions()
        print(f"Retrieved {len(z_positions)} Z position records from AF buffer")

        # Step 5: Stop AF and return to best position
        ti2.af_stop_zprint()
        print("Stopped AF Z-print motion")

        # Optional: Move to a specific AF index
        if z_positions:
            try:
                index_pos, z_dev = ti2.af_get_zprint_pos(1)
                print(f"AF slice 1 position: {index_pos}, Z={z_dev} (device units)")
            except Exception as e:
                print(f"Note: {e}")

        # Step 6: Stop AF completely
        ti2.af_stop()
        print("Stopped AF mode")

    print()


def example_autofocus_simple():
    """Example 14: Simple autofocus with callback"""
    print("=" * 70)
    print("EXAMPLE 14: Simple Autofocus with Live Callback")
    print("=" * 70)

    with NikonTi2() as ti2:
        # Define a live callback (would normally capture and analyze frames)
        frame_count = [0]

        def capture_callback():
            """Capture frame and return sharpness score"""
            frame_count[0] += 1
            # In real use:
            # image = camera.get_image()
            # sharpness = ti2.calculate_sharpness(image)
            # return sharpness
            print(f"  Frame {frame_count[0]} captured")
            return None

        # Run autofocus
        print("Running autofocus scan (5 steps)...")
        success = ti2.autofocus(
            io_channel=1,
            speed=5,
            scan_duration_s=0.0,
            scan_half_range_um=20.0,
            scan_steps=5,
            live_callback=capture_callback,
            move_to_best=False,
            stop_on_sharpness_drop=False,
        )
        print(f"Autofocus completed: {success}")

    print()


# =============================================================================
# SECTION 7: Metadata
# =============================================================================

def example_metadata():
    """Example 18: Reading microscope metadata"""
    print("=" * 70)
    print("EXAMPLE 18: Microscope Metadata")
    print("=" * 70)

    with NikonTi2() as ti2:
        metadata = ti2.get_metadata()
        print(f"Metadata retrieved successfully")
        print(f"  Metadata usage mask: {hex(metadata.uiMetaDataUsageMask)}")
        print(f"  Equipment usage mask: {hex(metadata.sEquipmentControl.uiEquipmentUsageMask)}")

        # Access objective information
        for i in range(1):  # Check first objective slot
            obj = metadata.sNosepieceObjective[i]
            print(f"  Objective slot {i + 1}:")
            print(f"    Magnification: {obj.dMagnification:.1f}x")
            print(f"    NA: {obj.dNumericalAperture:.2f}")
            print(f"    PFS enabled: {obj.iIsPFSEnabled}")

    print()


# =============================================================================
# MAIN: Run all examples
# =============================================================================

def main():
    """Run all example functions"""
    print("\n")
    print("╔" + "=" * 68 + "╗")
    print("║" + " " * 68 + "║")
    print("║" + "  Nikon Ti2 Microscope Control - Examples".center(68) + "║")
    print("║" + " " * 68 + "║")
    print("╚" + "=" * 68 + "╝")
    print()

    examples = [
        ("Initialization", example_initialization),
        ("Context Manager", example_context_manager),
        ("Stage Positioning", example_stage_positioning),
        # ("Nosepiece Control", example_nosepiece_control),
        # ("Condenser Control", example_condenser_control),
        # ("Light Path Control", example_lightpath_control),
        ("Turret Control", example_turret_control),
        ("Filter Control", example_filter_control),
        # ("Shutter Control", example_shutter_control),
        ("DIA Lamp Control", example_dia_lamp_control),
        # ("EPI LED Control", example_epi_led_control),
        ("Metadata", example_metadata),
    ]

    print("Running 15 examples...\n")
    for i, (name, func) in enumerate(examples, 1):
        try:
            func()
        except Exception as e:
            print(f"ERROR in example '{name}': {e}\n")

    print("=" * 70)
    print("All examples completed!")
    print("=" * 70)


if __name__ == "__main__":
    main()
