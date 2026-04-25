import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from bluetooth_2_usb import capture_device


class CaptureDeviceCliTest(unittest.TestCase):
    def test_capture_failures_are_reported_without_traceback(self) -> None:
        stderr = io.StringIO()

        with patch(
            "bluetooth_2_usb.capture_device.capture",
            side_effect=OSError("permission denied"),
        ):
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    capture_device.main(["--device", "/dev/input/missing"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("Failed to capture input device data", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
