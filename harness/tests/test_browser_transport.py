"""Fixture ports avoid ephemeral candidates without retrying failed runtime tests."""

import importlib.util
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "protohub_fixture_ports", ROOT / "tests/e2e/fixture_ports.py"
)
ports = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ports)


class FixturePortsTest(unittest.TestCase):
    def candidates(self, *values):
        remaining = iter(values)

        def draw(lower, upper):
            self.assertEqual((lower, upper), (20_000, 29_999))
            return next(remaining)

        return draw

    def test_random_source_is_limited_to_non_ephemeral_range(self):
        with (
            patch.object(ports.random, "SystemRandom") as random_source,
            patch.object(ports.socket, "socket") as listener,
        ):
            random_source.return_value.randint.side_effect = [20_001, 29_999]
            self.assertEqual(ports.choose_fixture_ports(), (20_001, 29_999))
            self.assertEqual(random_source.return_value.randint.call_count, 2)
            for call in random_source.return_value.randint.call_args_list:
                self.assertEqual(call.args, (20_000, 29_999))
            self.assertEqual(
                listener.return_value.bind.call_args_list[0].args,
                (("127.0.0.1", 20_001),),
            )
            self.assertEqual(
                listener.return_value.bind.call_args_list[1].args,
                (("127.0.0.1", 29_999),),
            )

    def test_occupied_loopback_candidate_is_skipped_with_real_sockets(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
            for candidate in range(20_000, 30_000):
                try:
                    occupied.bind(("127.0.0.1", candidate))
                    break
                except OSError:
                    continue
            else:
                self.fail("No local fixture-range port is available for the socket regression")
            # Search a bounded sequence after the real occupied socket, then wrap.
            candidates = [candidate, *range(candidate + 1, 30_000), *range(20_000, candidate)]
            selected = ports.choose_fixture_ports(
                candidate=self.candidates(*candidates), max_candidates=1024
            )
            self.assertNotIn(candidate, selected)
            self.assertEqual(len(set(selected)), 2)
            self.assertTrue(all(20_000 <= port <= 29_999 for port in selected))
        # The helper releases its reservations before returning to Docker.
        for port in selected:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as released:
                released.bind(("127.0.0.1", port))

    def test_duplicate_candidate_cannot_select_the_same_port_twice(self):
        with patch.object(ports.socket, "socket") as listener:
            selected = ports.choose_fixture_ports(
                candidate=self.candidates(20_010, 20_010, 20_011), max_candidates=3
            )
            self.assertEqual(selected, (20_010, 20_011))
            self.assertEqual(listener.call_count, 2)

    def test_exhaustion_fails_with_bounded_attempts_and_closes_rejections(self):
        with patch.object(ports.socket, "socket") as listener:
            listener.return_value.bind.side_effect = OSError("synthetic occupied port")
            with self.assertRaisesRegex(ports.PortSelectionError, "after 3 candidates"):
                ports.choose_fixture_ports(
                    candidate=self.candidates(20_020, 20_021, 20_022), max_candidates=3
                )
            self.assertEqual(listener.call_count, 3)
            self.assertEqual(listener.return_value.close.call_count, 3)

    def test_duplicate_only_exhaustion_releases_the_first_reservation(self):
        with patch.object(ports.socket, "socket") as listener:
            with self.assertRaises(ports.PortSelectionError):
                ports.choose_fixture_ports(
                    candidate=self.candidates(20_030, 20_030), max_candidates=2
                )
            self.assertEqual(listener.call_count, 1)
            listener.return_value.__exit__.assert_called_once()

    def test_ephemeral_candidate_is_rejected_before_any_socket_is_created(self):
        with patch.object(ports.socket, "socket") as listener:
            with self.assertRaisesRegex(ValueError, "outside the fixture range"):
                ports.choose_fixture_ports(candidate=self.candidates(58_867), max_candidates=1)
            listener.assert_not_called()

    def test_candidate_budget_must_be_positive_and_bounded(self):
        for value in (0, -1, 1025, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ports.choose_fixture_ports(max_candidates=value)


if __name__ == "__main__":
    unittest.main()
