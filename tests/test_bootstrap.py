"""Tests for the rules behind handing a panel its bootstrap.

Everything here decides what Home Assistant sends to a device on the local
network, and one of the three values is an access token. The rules are worth
more than the aiohttp calls around them, which is why they live in a module
with no Home Assistant imports.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "media_controller"
    / "bootstrap.py"
)
SPEC = importlib.util.spec_from_file_location(
    "media_controller_bootstrap", MODULE_PATH
)
assert SPEC is not None and SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = bootstrap
SPEC.loader.exec_module(bootstrap)


# A token-shaped value, so the tests are not accidentally passing because
# every value is refused.
TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJhYmMifQ.c2lnbmF0dXJlLWhlcmU"


class StatusTests(unittest.TestCase):
    """Verify what a panel's answer means to the person at the form."""

    def test_agreement_is_not_an_error(self) -> None:
        self.assertIsNone(bootstrap.error_for_status(200))

    def test_each_refusal_is_named(self) -> None:
        for status, expected in (
            (403, bootstrap.ERROR_CODE_MISMATCH),
            (409, bootstrap.ERROR_ALREADY_PAIRED),
            (429, bootstrap.ERROR_TOO_MANY_ATTEMPTS),
            (503, bootstrap.ERROR_NOT_READY),
        ):
            with self.subTest(status=status):
                self.assertEqual(bootstrap.error_for_status(status), expected)

    def test_an_unexpected_status_is_not_guessed_at(self) -> None:
        for status in (201, 302, 400, 404, 500, 502):
            with self.subTest(status=status):
                self.assertEqual(
                    bootstrap.error_for_status(status),
                    bootstrap.ERROR_REFUSED,
                )


class UrlTests(unittest.TestCase):
    """Verify the address rule, which mirrors the device's own."""

    def test_an_origin_is_kept(self) -> None:
        for value in (
            "http://192.168.1.10:8123",
            "https://ha.example:8123",
            "http://homeassistant.local:8123",
        ):
            with self.subTest(value=value):
                self.assertEqual(bootstrap.normalise_url(value), value)

    def test_a_trailing_slash_is_forgiven(self) -> None:
        self.assertEqual(
            bootstrap.normalise_url("http://192.168.1.10:8123/"),
            "http://192.168.1.10:8123",
        )

    def test_surrounding_space_is_forgiven(self) -> None:
        self.assertEqual(
            bootstrap.normalise_url("  http://10.0.0.2:8123  "),
            "http://10.0.0.2:8123",
        )

    def test_a_path_is_refused(self) -> None:
        # The panel appends its own path, so an address carrying one could
        # redirect a request meant for /api/states/ somewhere else.
        self.assertEqual(
            bootstrap.normalise_url("http://192.168.1.10:8123/local/x"), ""
        )

    def test_another_scheme_is_refused(self) -> None:
        for value in (
            "ftp://192.168.1.10",
            "192.168.1.10:8123",
            "javascript:alert(1)",
            "//192.168.1.10",
        ):
            with self.subTest(value=value):
                self.assertEqual(bootstrap.normalise_url(value), "")

    def test_an_empty_host_is_refused(self) -> None:
        self.assertEqual(bootstrap.normalise_url("http://"), "")
        self.assertEqual(bootstrap.normalise_url("http:///"), "")

    def test_embedded_whitespace_is_refused(self) -> None:
        self.assertEqual(
            bootstrap.normalise_url("http://192.168.1.10 :8123"), ""
        )
        self.assertEqual(
            bootstrap.normalise_url("http://192.168.1.10\r\nX: y"), ""
        )

    def test_an_over_long_address_is_refused(self) -> None:
        long_host = "a" * bootstrap.MAX_URL_CHARS
        self.assertEqual(bootstrap.normalise_url(f"http://{long_host}"), "")

    def test_a_non_string_is_refused(self) -> None:
        for value in (None, 8123, [], {}):
            with self.subTest(value=value):
                self.assertEqual(bootstrap.normalise_url(value), "")


class TokenTests(unittest.TestCase):
    """Verify that only something token-shaped reaches a request header."""

    def test_a_jwt_is_accepted(self) -> None:
        self.assertTrue(bootstrap.is_plausible_token(TOKEN))

    def test_the_wrong_number_of_segments_is_refused(self) -> None:
        self.assertFalse(bootstrap.is_plausible_token("abc.def"))
        self.assertFalse(bootstrap.is_plausible_token("a.b.c.d"))

    def test_an_empty_segment_is_refused(self) -> None:
        self.assertFalse(bootstrap.is_plausible_token("abc..def"))

    def test_a_header_break_is_refused(self) -> None:
        self.assertFalse(bootstrap.is_plausible_token("abc.de\r\nf.ghi"))
        self.assertFalse(bootstrap.is_plausible_token("abc.de f.ghi"))

    def test_an_over_long_token_is_refused(self) -> None:
        segment = "a" * bootstrap.MAX_TOKEN_CHARS
        self.assertFalse(
            bootstrap.is_plausible_token(f"{segment}.{segment}.{segment}")
        )

    def test_nothing_is_refused(self) -> None:
        for value in ("", None, 12345):
            with self.subTest(value=value):
                self.assertFalse(bootstrap.is_plausible_token(value))


class EntityIdTests(unittest.TestCase):
    """Verify the config entity a panel is told to read."""

    def test_a_normal_entity_id_is_accepted(self) -> None:
        self.assertTrue(
            bootstrap.is_plausible_entity_id("sensor.living_room_config")
        )

    def test_a_path_separator_is_refused(self) -> None:
        self.assertFalse(
            bootstrap.is_plausible_entity_id("sensor.a/../../secret")
        )

    def test_upper_case_and_spaces_are_refused(self) -> None:
        self.assertFalse(bootstrap.is_plausible_entity_id("Sensor.Config"))
        self.assertFalse(bootstrap.is_plausible_entity_id("sensor.a b"))

    def test_the_wrong_number_of_parts_is_refused(self) -> None:
        self.assertFalse(bootstrap.is_plausible_entity_id("sensor"))
        self.assertFalse(bootstrap.is_plausible_entity_id("sensor.a.b"))
        self.assertFalse(bootstrap.is_plausible_entity_id(".config"))
        self.assertFalse(bootstrap.is_plausible_entity_id("sensor."))


class IdentityTests(unittest.TestCase):
    """Verify that a panel's own report about itself is read defensively."""

    def test_a_complete_report_is_read(self) -> None:
        identity = bootstrap.read_identity(
            {
                "panel_id": "AABBCCDDEEFF",
                "profile": "esp32_s3_panel",
                "name": "Kitchen",
                "version": "0.4.0",
                "contract_version": 7,
                "paired": False,
            }
        )
        assert identity is not None
        self.assertEqual(identity.panel_id, "AABBCCDDEEFF")
        self.assertEqual(identity.profile, "esp32_s3_panel")
        self.assertEqual(identity.contract_version, 7)
        self.assertFalse(identity.paired)

    def test_missing_fields_do_not_raise(self) -> None:
        identity = bootstrap.read_identity({"panel_id": "aabbcc"})
        assert identity is not None
        self.assertEqual(identity.profile, "")
        self.assertEqual(identity.name, "")
        self.assertEqual(identity.contract_version, 0)

    def test_a_nonsense_contract_version_becomes_zero(self) -> None:
        for value in ("seven", True, None, [7]):
            with self.subTest(value=value):
                identity = bootstrap.read_identity(
                    {"panel_id": "aabbcc", "contract_version": value}
                )
                assert identity is not None
                self.assertEqual(identity.contract_version, 0)

    def test_something_that_is_not_a_panel_is_no_identity(self) -> None:
        for payload in (None, [], "ok", {}, {"panel_id": ""}, {"panel_id": 5}):
            with self.subTest(payload=payload):
                self.assertIsNone(bootstrap.read_identity(payload))


class PushDecisionTests(unittest.TestCase):
    """Verify which panels may be posted to, and which are waited for."""

    IDENTITY = bootstrap.PanelIdentity(
        panel_id="AABBCCDDEEFF",
        profile="esp32_s3_panel",
        name="Kitchen",
        version="0.4.0",
        contract_version=7,
        paired=False,
    )

    def test_a_matching_panel_on_a_port_is_pushed_to(self) -> None:
        self.assertTrue(
            bootstrap.panel_accepts_push(80, self.IDENTITY, "aabbccddeeff")
        )

    def test_port_zero_is_waited_for(self) -> None:
        # This is the T560 tablet: it advertises port 0 because it serves
        # nothing, so the direction of pairing is decided by the record alone.
        self.assertFalse(
            bootstrap.panel_accepts_push(0, self.IDENTITY, "aabbccddeeff")
        )

    def test_a_silent_address_is_waited_for(self) -> None:
        self.assertFalse(bootstrap.panel_accepts_push(80, None, "aabbccddeeff"))

    def test_another_panel_on_that_address_is_not_pushed_to(self) -> None:
        self.assertFalse(
            bootstrap.panel_accepts_push(80, self.IDENTITY, "112233445566")
        )


class DeliveryPlanTests(unittest.TestCase):
    """Verify what has to be true before a token leaves Home Assistant."""

    def _plan(self, **overrides):
        arguments = {
            "host": "192.168.1.44",
            "port": 80,
            "pending": ("123456", TOKEN),
            "ha_url": "http://192.168.1.10:8123",
            "config_entity": "sensor.kitchen_config",
        }
        arguments.update(overrides)
        return bootstrap.plan_delivery(**arguments)

    def test_a_complete_plan_carries_everything(self) -> None:
        delivery, blocked = self._plan()
        self.assertIsNone(blocked)
        assert delivery is not None
        self.assertEqual(
            delivery.as_body(),
            {
                "code": "123456",
                "ha_url": "http://192.168.1.10:8123",
                "token": TOKEN,
                "config_entity": "sensor.kitchen_config",
            },
        )

    def test_nothing_pending_is_the_ordinary_case(self) -> None:
        delivery, blocked = self._plan(pending=None)
        self.assertIsNone(delivery)
        self.assertEqual(blocked, bootstrap.BLOCKED_NOT_PENDING)

    def test_a_panel_that_serves_nothing_is_not_pushed_to(self) -> None:
        for overrides in ({"port": 0}, {"host": ""}):
            with self.subTest(overrides=overrides):
                delivery, blocked = self._plan(**overrides)
                self.assertIsNone(delivery)
                self.assertEqual(blocked, bootstrap.BLOCKED_NO_ADDRESS)

    def test_no_address_is_a_panel_that_polls_and_not_a_failure(self) -> None:
        """The distinction that turned a pairing into an endless loop.

        `plan_delivery` refuses to push to a panel with no address, and that
        refusal is correct. What was wrong was what the caller did with it:
        any blocked reason with a pairing waiting was treated as a failed
        provisioning, which revoked the token that had just been minted and
        started reauthentication -- which minted another token, which was
        revoked in turn.

        The panel sat on its pairing screen through every round of it, because
        the one thing that would have ended it was the token waiting to be
        collected, and that was destroyed a moment after each was created.

        "No address" is the whole description of a panel that collects its own
        token by polling: the T560 tablet always, and an ESP32 whose port could
        not be probed at the moment somebody typed the code. The reason is
        therefore its own value rather than one of a set to be lumped
        together, and `async_deliver_bootstrap` branches on it.
        """
        for overrides in ({"port": 0}, {"host": ""}):
            with self.subTest(overrides=overrides):
                delivery, blocked = self._plan(**overrides)
                self.assertIsNone(delivery)
                self.assertEqual(blocked, bootstrap.BLOCKED_NO_ADDRESS)
                # Not the same answer as any other refusal, because the caller
                # has to tell it apart from one.
                self.assertNotEqual(blocked, bootstrap.BLOCKED_NOT_PENDING)
                self.assertNotEqual(blocked, bootstrap.BLOCKED_NO_URL)
                self.assertNotEqual(
                    blocked, bootstrap.BLOCKED_NO_CONFIG_ENTITY
                )

    def test_the_delivery_leaves_a_pollable_panel_alone(self) -> None:
        """The caller's half of the rule above, checked where it is written.

        `panel_provision.py` needs a Home Assistant runtime, which this suite
        does not have, so what is pinned here is the branch itself: that the
        one reason a panel may be left to poll is told apart from the reasons
        that revoke its token.
        """
        source = (
            Path(__file__).parents[1]
            / "custom_components"
            / "media_controller"
            / "panel_provision.py"
        ).read_text(encoding="utf-8")
        deliver = source[source.index("async def async_deliver_bootstrap") :]
        deliver = deliver[: deliver.index("\nasync def _async_check_still_paired")]
        self.assertIn("if blocked == BLOCKED_NO_ADDRESS:", deliver)
        # And the branch has to come before the one that throws the token
        # away, or it never runs.
        self.assertLess(
            deliver.index("if blocked == BLOCKED_NO_ADDRESS:"),
            deliver.index("_async_abandon"),
        )

    def test_no_address_stops_the_delivery(self) -> None:
        for value in (None, "", "not-a-url"):
            with self.subTest(value=value):
                delivery, blocked = self._plan(ha_url=value)
                self.assertIsNone(delivery)
                self.assertEqual(blocked, bootstrap.BLOCKED_NO_URL)

    def test_no_config_sensor_stops_the_delivery(self) -> None:
        delivery, blocked = self._plan(config_entity="")
        self.assertIsNone(delivery)
        self.assertEqual(blocked, bootstrap.BLOCKED_NO_CONFIG_ENTITY)

    def test_a_malformed_token_is_never_sent(self) -> None:
        delivery, blocked = self._plan(pending=("123456", "not a token"))
        self.assertIsNone(delivery)
        self.assertEqual(blocked, bootstrap.BLOCKED_NOT_PENDING)

    def test_the_address_is_normalised_before_it_is_sent(self) -> None:
        delivery, _ = self._plan(ha_url="http://192.168.1.10:8123/")
        assert delivery is not None
        self.assertEqual(delivery.ha_url, "http://192.168.1.10:8123")


if __name__ == "__main__":
    unittest.main()
