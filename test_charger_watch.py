import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib import error

import charger_watch as watch


class FakeResponse:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, *_):
        return self._body


def api_response(*chargers):
    return FakeResponse({"entities": list(chargers)})


class StatusTest(unittest.TestCase):
    def fetch(self, response):
        with patch.object(watch.request, "urlopen", return_value=response):
            return watch.fetch_status("EVS-1234")

    def test_available_port_only(self):
        charger = {"name": "EVS-1234", "maintenanceFlag": False,
                   "ports": [{"status": "SESSION"}, {"status": "AVAILABLE"}]}
        self.assertTrue(self.fetch(api_response(charger)))

    def test_no_available_port(self):
        charger = {"name": "EVS-1234", "ports": [{"status": "SESSION"}, {"status": "FAULTED"}]}
        self.assertFalse(self.fetch(api_response(charger)))

    def test_maintenance_is_not_available(self):
        charger = {"name": "EVS-1234", "maintenanceFlag": True, "ports": [{"status": "AVAILABLE"}]}
        self.assertFalse(self.fetch(api_response(charger)))

    def test_name_match_is_case_insensitive_and_exact(self):
        chargers = [{"name": "evs-1234", "ports": [{"status": "AVAILABLE"}]},
                    {"name": "EVS-12345", "ports": [{"status": "SESSION"}]}]
        self.assertTrue(self.fetch(api_response(*chargers)))

    def test_missing_charger_raises(self):
        with self.assertRaises(ValueError):
            self.fetch(api_response())

    def test_malformed_response_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.fetch(FakeResponse(["not", "a", "dict"]))


class NotificationTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "state.json"

    def test_alerts_once_per_change(self):
        with patch.object(watch, "fetch_status", side_effect=[False, True, True, False, False, True]), \
             patch.object(watch, "send_serverchan") as send:
            for _ in range(6):
                watch.check_once(["EVS-1234"], "SCTkey", self.state)
        self.assertEqual([c.kwargs["available"] for c in send.call_args_list], [True, False, True])

    def test_failed_occupied_send_is_retried(self):
        watch.write_state(self.state, {"EVS-1234": True})
        with patch.object(watch, "fetch_status", return_value=False), \
             patch.object(watch, "send_serverchan", side_effect=[RuntimeError("failed"), None]) as send:
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
            self.assertTrue(watch.read_state(self.state)["EVS-1234"])
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
        self.assertEqual(send.call_count, 2)
        self.assertFalse(watch.read_state(self.state)["EVS-1234"])

    def test_failed_send_is_retried(self):
        with patch.object(watch, "fetch_status", return_value=True), \
             patch.object(watch, "send_serverchan", side_effect=[RuntimeError("failed"), None]) as send:
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
        self.assertEqual(send.call_count, 2)
        self.assertTrue(watch.read_state(self.state)["EVS-1234"])

    def test_failed_check_keeps_previous_state(self):
        watch.write_state(self.state, {"EVS-1234": True})
        with patch.object(watch, "fetch_status", side_effect=error.URLError("down")), \
             patch.object(watch, "send_serverchan") as send:
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
        send.assert_not_called()
        self.assertTrue(watch.read_state(self.state)["EVS-1234"])

    def test_one_bad_charger_does_not_block_others(self):
        def fetch(name, _api_url):
            if name == "EVS-1":
                raise KeyError("surprise")
            return True

        with patch.object(watch, "fetch_status", side_effect=fetch), \
             patch.object(watch, "send_serverchan") as send, \
             self.assertLogs(watch.LOG, "ERROR"):
            watch.check_once(["EVS-1", "EVS-2"], "SCTkey", self.state)
        send.assert_called_once_with("EVS-2", "SCTkey", available=True)

    def test_corrupt_state_file_is_ignored(self):
        self.state.write_text("{not json")
        with patch.object(watch, "fetch_status", return_value=True), \
             patch.object(watch, "send_serverchan") as send, \
             self.assertLogs(watch.LOG, "WARNING"):
            watch.check_once(["EVS-1234"], "SCTkey", self.state)
        send.assert_called_once()
        self.assertEqual(watch.read_state(self.state), {"EVS-1234": True})


class ServerChanTest(unittest.TestCase):
    def test_http_error_does_not_leak_sendkey(self):
        exc = error.HTTPError("https://sctapi.ftqq.com/SCTsecret.send", 500, "boom", {}, None)
        with patch.object(watch.request, "urlopen", side_effect=exc):
            with self.assertRaises(RuntimeError) as caught:
                watch.send_serverchan("EVS-1234", "SCTsecret")
        self.assertNotIn("SCTsecret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_rejected_message_raises(self):
        with patch.object(watch.request, "urlopen", return_value=FakeResponse({"code": 40001})):
            with self.assertRaises(RuntimeError):
                watch.send_serverchan("EVS-1234", "SCTsecret")


if __name__ == "__main__":
    unittest.main()
