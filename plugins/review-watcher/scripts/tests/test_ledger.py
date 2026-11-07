import json
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import gh_client  # noqa: E402
import ledger  # noqa: E402


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "ledger.json")
        self.poller = os.path.join(self.tmp.name, "poller.lock")

    def tearDown(self):
        self.tmp.cleanup()

    def test_should_round_trip_through_update(self):
        with ledger.update(self.path) as data:
            data["seen"]["acme/widgets#1"] = "2026-10-01T00:00:00Z"
            data["active"]["acme/widgets#1"] = {"session": "Rev PR#1 acme/widgets"}
        self.assertEqual(ledger.read(self.path)["seen"], {"acme/widgets#1": "2026-10-01T00:00:00Z"})
        self.assertEqual(ledger.read(self.path)["active"]["acme/widgets#1"]["session"], "Rev PR#1 acme/widgets")
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_should_start_flat_with_seen_active_and_done(self):
        self.assertEqual(ledger.empty(), {"seen": {}, "active": {}, "done": {}})
        self.assertEqual(ledger.read(os.path.join(self.tmp.name, "missing.json")), ledger.empty())

    def test_should_fill_missing_or_malformed_sections(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump({"seen": {"a/b#1": "x"}, "active": [], "other": 1}, fh)
        data = ledger.read(self.path)
        self.assertEqual(data["seen"], {"a/b#1": "x"})
        self.assertEqual(data["active"], {})
        self.assertEqual(data["done"], {})
        self.assertEqual(data["other"], 1)

    def test_should_be_readable_by_the_scan_loader(self):
        with ledger.update(self.path) as data:
            data["seen"]["acme/widgets#1"] = "2026-10-01T00:00:00Z"
        self.assertEqual(gh_client.load_state(self.path)["seen"], {"acme/widgets#1": "2026-10-01T00:00:00Z"})

    def test_should_raise_a_state_error_for_a_corrupt_ledger(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("{broken")
        with self.assertRaises(gh_client.StateError):
            ledger.read(self.path)
        with self.assertRaises(gh_client.StateError):
            with ledger.update(self.path):
                pass
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "{broken")

    def test_should_time_out_while_the_writer_lock_is_held(self):
        with open(self.path + ".lock", "w", encoding="utf-8") as fh:
            fh.write("{}")
        with self.assertRaises(ledger.LedgerBusy):
            with ledger.update(self.path, timeout=0.2):
                self.fail("must not enter the block")

    def test_should_break_a_stale_writer_lock(self):
        lock = self.path + ".lock"
        with open(lock, "w", encoding="utf-8") as fh:
            fh.write("{}")
        old = time.time() - ledger.WRITER_LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        with ledger.update(self.path, timeout=1) as data:
            data["seen"]["a/b#1"] = "x"
        self.assertEqual(ledger.read(self.path)["seen"], {"a/b#1": "x"})

    def write_lock(self, token):
        lock = self.path + ".lock"
        with open(lock, "w", encoding="utf-8") as fh:
            json.dump({"pid": 1, "at": 0, "token": token}, fh)
        return lock

    def leftovers(self):
        return [name for name in os.listdir(self.tmp.name) if name.endswith(".grave")]

    def test_should_not_remove_a_lock_that_changed_after_it_was_judged_stale(self):
        stale = (None, 1)
        lock = self.write_lock("fresh")
        self.assertFalse(ledger._remove_if(lock, lambda state: state == stale))
        self.assertEqual(ledger._lock_state(lock)[0], "fresh")
        self.assertEqual(self.leftovers(), [])

    def test_should_remove_the_lock_it_judged_stale(self):
        lock = self.write_lock("old")
        stale = ledger._lock_state(lock)
        self.assertTrue(ledger._remove_if(lock, lambda state: state == stale))
        self.assertFalse(os.path.exists(lock))
        self.assertEqual(self.leftovers(), [])

    def test_should_release_only_its_own_writer_lock(self):
        with ledger.update(self.path) as data:
            data["seen"]["a/b#1"] = "x"
            self.write_lock("another-writer")
        self.assertEqual(ledger._lock_state(self.path + ".lock")[0], "another-writer")
        self.assertEqual(self.leftovers(), [])

    def test_should_keep_a_lock_replaced_after_the_stale_one_was_read(self):
        lock = self.write_lock("old")
        old = time.time() - ledger.WRITER_LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        real_lock_state = ledger._lock_state
        swapped = []

        def lock_state(path):
            state = real_lock_state(path)
            if path == lock and not swapped:
                replacement = lock + ".new"
                with open(replacement, "w", encoding="utf-8") as fh:
                    json.dump({"pid": 2, "at": 0, "token": "fresh"}, fh)
                os.replace(replacement, lock)
                swapped.append(True)
            return state

        with mock.patch.object(ledger, "_lock_state", side_effect=lock_state), \
                self.assertRaises(ledger.LedgerBusy), ledger.update(self.path, timeout=0.2):
            self.fail("must not enter the block")
        self.assertEqual(swapped, [True])
        self.assertEqual(real_lock_state(lock)[0], "fresh")
        self.assertEqual(self.leftovers(), [])

    def test_should_time_out_when_a_stale_writer_lock_cannot_be_removed(self):
        lock = self.write_lock("old")
        old = time.time() - ledger.WRITER_LOCK_STALE_SECONDS - 5
        os.utime(lock, (old, old))
        with mock.patch.object(ledger, "_remove_if", return_value=False):
            with self.assertRaises(ledger.LedgerBusy):
                with ledger.update(self.path, timeout=0.2):
                    self.fail("must not enter the block")

    def test_should_record_a_token_in_the_writer_lock(self):
        with ledger.update(self.path):
            token = ledger._lock_state(self.path + ".lock")[0]
        self.assertRegex(token, r"^[0-9a-f]{32}$")

    def test_should_not_write_when_the_block_raises(self):
        with ledger.update(self.path) as data:
            data["seen"]["a/b#1"] = "x"
        with self.assertRaises(RuntimeError):
            with ledger.update(self.path) as data:
                data["seen"]["a/b#2"] = "y"
                raise RuntimeError("boom")
        self.assertEqual(ledger.read(self.path)["seen"], {"a/b#1": "x"})
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_should_retry_replace_after_a_permission_error(self):
        attempts = []

        def flaky_replace(src, dst):
            attempts.append(1)
            if len(attempts) < 3:
                raise PermissionError("WinError 5")
            os.replace(src, dst)

        ledger.write_atomic(self.path, {"seen": {"a/b#1": "x"}}, replace=flaky_replace, sleep=lambda s: None)
        self.assertEqual(len(attempts), 3)
        with open(self.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"seen": {"a/b#1": "x"}})

    def test_should_remove_the_temp_file_when_replace_keeps_failing(self):
        def always_denied(src, dst):
            raise PermissionError("WinError 5")

        with self.assertRaises(PermissionError):
            ledger.write_atomic(self.path, {}, replace=always_denied, sleep=lambda s: None)
        self.assertEqual(os.listdir(self.tmp.name), [])

    def test_should_never_write_from_a_snapshot(self):
        with ledger.update(self.path) as data:
            data["seen"]["a/b#1"] = "x"
        with open(self.path, "rb") as fh:
            before = fh.read()
        with ledger.snapshot(self.path) as data:
            data["seen"]["a/b#2"] = "y"
        with open(self.path, "rb") as fh:
            self.assertEqual(fh.read(), before)
        self.assertFalse(os.path.exists(self.path + ".lock"))

    def test_should_keep_the_poller_stale_window_longer_than_a_scan(self):
        self.assertGreater(ledger.POLLER_STALE_SECONDS, ledger.SCAN_TIMEOUT_SECONDS)

    def test_should_refuse_a_second_poller_while_the_first_is_fresh(self):
        ledger.acquire_poller(self.poller, now=1000.0, pid=11)
        with self.assertRaises(ledger.PollerRunning) as raised:
            ledger.acquire_poller(self.poller, now=1100.0, pid=22)
        self.assertEqual(raised.exception.pid, 11)
        self.assertEqual(raised.exception.age, 100.0)

    def test_should_take_over_a_stale_or_unreadable_poller_lock(self):
        ledger.acquire_poller(self.poller, now=1000.0, pid=11)
        token = ledger.acquire_poller(self.poller, now=1000.0 + ledger.POLLER_STALE_SECONDS + 1, pid=22)
        self.assertEqual(token["pid"], 22)
        with open(self.poller, "w", encoding="utf-8") as fh:
            fh.write("garbage")
        self.assertEqual(ledger.acquire_poller(self.poller, now=5000.0, pid=33)["pid"], 33)

    def test_should_link_the_poller_lock_into_place_with_its_body_already_written(self):
        bodies = []
        real_link = os.link

        def link(src, dst):
            with open(src, encoding="utf-8") as fh:
                bodies.append(json.load(fh))
            real_link(src, dst)

        with mock.patch("ledger.os.link", side_effect=link):
            ledger.acquire_poller(self.poller, now=1000.0, pid=11)
        self.assertEqual(bodies, [{"pid": 11, "started_at": 1000.0, "heartbeat_at": 1000.0}])
        self.assertEqual(os.listdir(self.tmp.name), ["poller.lock"])

    def test_should_not_take_over_a_lock_another_watcher_replaced_after_the_stale_read(self):
        ledger.acquire_poller(self.poller, now=1000.0, pid=11)
        os.utime(self.poller, (1000.0, 1000.0))
        later = 1000.0 + ledger.POLLER_STALE_SECONDS + 1
        real_read = ledger._read_poller
        raced = []

        def read_then_lose_the_race(path):
            stale = real_read(path)
            if not raced:
                raced.append(None)
                raced[0] = ledger.acquire_poller(self.poller, now=later, pid=22)
            return stale

        with mock.patch("ledger._read_poller", side_effect=read_then_lose_the_race):
            with self.assertRaises(ledger.PollerRunning) as raised:
                ledger.acquire_poller(self.poller, now=later, pid=33)
        self.assertEqual(raised.exception.pid, 22)
        self.assertEqual(raced[0]["pid"], 22)
        with open(self.poller, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["pid"], 22)
        self.assertTrue(ledger.heartbeat(self.poller, raced[0], now=later + 1))
        self.assertEqual(os.listdir(self.tmp.name), ["poller.lock"])

    def test_should_heartbeat_and_release_only_its_own_lock(self):
        mine = ledger.acquire_poller(self.poller, now=1000.0, pid=11)
        self.assertTrue(ledger.heartbeat(self.poller, mine, now=1500.0))
        with open(self.poller, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["heartbeat_at"], 1500.0)
        foreign = {"pid": 99, "started_at": 1.0}
        self.assertFalse(ledger.heartbeat(self.poller, foreign, now=1600.0))
        ledger.release(self.poller, foreign)
        self.assertTrue(os.path.exists(self.poller))
        ledger.release(self.poller, mine)
        self.assertFalse(os.path.exists(self.poller))
        self.assertFalse(ledger.heartbeat(self.poller, mine, now=1700.0))

    def test_should_never_signal_a_process_to_check_liveness(self):
        with mock.patch("os.kill", side_effect=AssertionError("os.kill must not be called")):
            ledger.acquire_poller(self.poller, now=1000.0, pid=11)
            ledger.acquire_poller(self.poller, now=1000.0 + ledger.POLLER_STALE_SECONDS + 1, pid=22)
            with self.assertRaises(ledger.PollerRunning):
                ledger.acquire_poller(self.poller, now=1000.0 + ledger.POLLER_STALE_SECONDS + 2, pid=33)


if __name__ == "__main__":
    unittest.main()
