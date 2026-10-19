import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import charger_watch as watch


class StatusTest(unittest.TestCase):
    def test_available_port_only(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, *_):
                return json.dumps({"entities": [{"name": "EVS-1234", "maintenanceFlag": False,
                                                 "ports": [{"status": "SESSION"}, {"status": "AVAILABLE"}]}]}).encode()

        with patch.object(watch.request, "urlopen", return_value=Response()):
            self.assertTrue(watch.fetch_status("EVS-1234"))

    def test_maintenance_is_not_available(self):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def read(self, *_):
                return json.dumps({"entities": [{"name": "EVS-1234", "maintenanceFlag": True,
                                                 "ports": [{"status": "AVAILABLE"}]}]}).encode()

        with patch.object(watch.request, "urlopen", return_value=Response()):
            self.assertFalse(watch.fetch_status("EVS-1234"))


class NotificationTest(unittest.TestCase):
    def test_alerts_once_per_available_period(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with patch.object(watch, "fetch_status", side_effect=[False, True, True, False, True]), \
                 patch.object(watch, "send_serverchan") as send:
                for _ in range(5):
                    watch.check_once(["EVS-1234"], "SCTkey", state)
            self.assertEqual(send.call_count, 2)

    def test_failed_send_is_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state.json"
            with patch.object(watch, "fetch_status", return_value=True), \
                 patch.object(watch, "send_serverchan", side_effect=[RuntimeError("failed"), None]) as send:
                watch.check_once(["EVS-1234"], "SCTkey", state)
                watch.check_once(["EVS-1234"], "SCTkey", state)
            self.assertEqual(send.call_count, 2)
            self.assertTrue(watch.read_state(state)["EVS-1234"])


if __name__ == "__main__":
    unittest.main()
