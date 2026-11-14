import unittest

from hr_measurement import HeartRateMeasurement, bpm_period_ms, display_period_ms, parse_heart_rate


class HeartRateMeasurementTests(unittest.TestCase):
    def test_uint8_and_unsupported_contact(self):
        self.assertEqual(
            parse_heart_rate(bytes.fromhex("00 48")),
            HeartRateMeasurement(72, None, ()),
        )

    def test_uint16_is_little_endian(self):
        self.assertEqual(
            parse_heart_rate(bytes.fromhex("01 2c 01")),
            HeartRateMeasurement(300, None, ()),
        )

    def test_contact_requires_the_support_bit(self):
        for flags, expected in ((0x00, None), (0x02, None), (0x04, False), (0x06, True)):
            with self.subTest(flags=flags):
                self.assertIs(parse_heart_rate(bytes((flags, 72))).contact, expected)

    def test_energy_is_skipped_before_rr_intervals(self):
        self.assertEqual(
            parse_heart_rate(bytes.fromhex("1e 48 ff ff 00 04 00 03")),
            HeartRateMeasurement(72, True, (1.0, 0.75)),
        )

    def test_uint16_energy_and_rr_can_be_combined(self):
        self.assertEqual(
            parse_heart_rate(bytes.fromhex("1f 2c 01 01 00 80 00")),
            HeartRateMeasurement(300, True, (0.125,)),
        )

    def test_rr_without_energy(self):
        self.assertEqual(parse_heart_rate(bytes.fromhex("10 48 01 04")).rr_seconds, (1025 / 1024,))

    def test_energy_without_rr(self):
        self.assertEqual(
            parse_heart_rate(bytes.fromhex("08 48 00 01")),
            HeartRateMeasurement(72, None, ()),
        )

    def test_zero_is_preserved_for_the_consumer_to_handle(self):
        self.assertEqual(parse_heart_rate(bytes.fromhex("00 00")).bpm, 0)

    def test_rejects_incomplete_fields(self):
        payloads = (
            "",                 # No flags.
            "00",               # Missing uint8 BPM.
            "01 48",            # Truncated uint16 BPM.
            "08 48",            # Missing Energy Expended.
            "08 48 01",         # Truncated Energy Expended.
            "10 48",            # RR flag requires at least one interval.
            "10 48 00",         # Truncated RR interval.
            "10 48 00 04 00",   # Truncated second RR interval.
            "18 48 01 00",      # Energy present but RR missing.
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_heart_rate(bytes.fromhex(payload))

    def test_rejects_trailing_data_without_rr_flag(self):
        for payload in ("00 48 00", "01 2c 01 00", "08 48 00 00 01 02"):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_heart_rate(bytes.fromhex(payload))

    def test_rejects_reserved_flags(self):
        for flag in (0x20, 0x40, 0x80):
            with self.subTest(flag=flag):
                with self.assertRaises(ValueError):
                    parse_heart_rate(bytes((flag, 72)))


class BpmPeriodTests(unittest.TestCase):
    def test_periods_and_firmware_boundaries(self):
        for bpm, expected in ((6, 10000), (60, 1000), (72, 833), (120, 500), (128, 469), (600, 100)):
            with self.subTest(bpm=bpm):
                self.assertEqual(bpm_period_ms(bpm), expected)

    def test_rejects_unrepresentable_or_noninteger_values(self):
        for bpm in (-1, 0, 5, 601, 65535, 72.5, True, "72"):
            with self.subTest(bpm=bpm):
                with self.assertRaises(ValueError):
                    bpm_period_ms(bpm)


class DisplayPeriodTests(unittest.TestCase):
    def test_every_display_band_includes_both_boundaries(self):
        bands = (
            (6, 70, 1000),
            (71, 75, 900),
            (76, 80, 800),
            (81, 85, 700),
            (86, 90, 600),
            (91, 95, 500),
            (96, 100, 400),
            (101, 105, 300),
            (106, 110, 200),
            (111, 600, 100),
        )
        for lower, upper, expected in bands:
            for bpm in (lower, (lower + upper) // 2, upper):
                with self.subTest(bpm=bpm):
                    self.assertEqual(display_period_ms(bpm), expected)

    def test_rejects_the_same_invalid_inputs_as_actual_heartbeat_period(self):
        for bpm in (-1, 0, 5, 601, 65535, 72.5, float("nan"), True, False, "72", None):
            with self.subTest(bpm=bpm):
                with self.assertRaises(ValueError):
                    display_period_ms(bpm)
                with self.assertRaises(ValueError):
                    bpm_period_ms(bpm)


if __name__ == "__main__":
    unittest.main()
