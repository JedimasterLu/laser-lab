"""Opt-in integration tests for a real Nikon Ti2 microscope.

Run with a connected microscope and the SDK DLL available::

    LASERLAB_TI2_HARDWARE=1 pytest tests/test_ti2_hardware.py -q

Set LASERLAB_TI2_DLL when the DLL is not in the wrapper's default locations.
These tests are intentionally skipped by default and never use the simulator.
"""

from __future__ import annotations

import os
import unittest

from laserlab.ti2 import NikonTi2


@unittest.skipUnless(
    os.environ.get("LASERLAB_TI2_HARDWARE") == "1",
    "set LASERLAB_TI2_HARDWARE=1 to run real Ti2 integration tests",
)
class TestTi2Hardware(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.ti2 = NikonTi2(
            dll_path=os.environ.get("LASERLAB_TI2_DLL"),
            simulator=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ti2.close()

    def test_metadata_get_from_real_ti2(self) -> None:
        metadata = self.ti2.get_metadata()

        self.assertIsInstance(metadata.uiMetaDataUsageMask, int)
        self.assertEqual(len(metadata.iZDrive_RangePhys), 2)
        self.assertEqual(len(metadata.iXYStage_XRangePhys), 2)
        self.assertEqual(len(metadata.iXYStage_YRangePhys), 2)
        self.assertLessEqual(metadata.iZDrive_RangePhys[0], metadata.iZDrive_RangePhys[1])

    def test_read_xy_and_optical_state_from_real_ti2(self) -> None:
        self.assertIsInstance(self.ti2.get_x(), float)
        self.assertIsInstance(self.ti2.get_y(), float)
        self.assertIn(self.ti2.get_nosepiece(), range(1, 7))
        self.assertIn(self.ti2.get_condenser(), range(1, 8))
        self.assertIn(self.ti2.get_lightpath(), range(1, 5))
        self.assertIsInstance(self.ti2.get_shutter("epi"), bool)
        self.assertIsInstance(self.ti2.get_shutter("dia"), bool)
        self.assertIsInstance(self.ti2.get_shutter("aux"), bool)


if __name__ == "__main__":
    unittest.main()
