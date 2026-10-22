# -*- encoding: utf-8 -*-
from odoo.addons.eh_hr_attendance_base.tests.common import EhHrTestCommon
from odoo.addons.eh_hr_face_kiosk.controllers.face_match import (
    _normalise,
    _cosine_distance,
    _haversine_meters,
)


class TestMatchMath(EhHrTestCommon):
    """Pure-Python helpers used by the match endpoint. Testable without
    spinning up the HTTP layer."""

    def test_normalise_unit_length(self):
        v = _normalise([3.0, 4.0])
        norm = sum(x * x for x in v) ** 0.5
        self.assertAlmostEqual(norm, 1.0, places=6)

    def test_cosine_distance_self_zero(self):
        v = _normalise(self._make_embedding(seed=42))
        self.assertAlmostEqual(_cosine_distance(v, v), 0.0, places=6)

    def test_cosine_distance_opposite_two(self):
        v = _normalise([1.0] + [0.0] * 127)
        w = _normalise([-1.0] + [0.0] * 127)
        self.assertAlmostEqual(_cosine_distance(v, w), 2.0, places=6)

    def test_haversine_zero_distance(self):
        d = _haversine_meters(-37.8136, 144.9631, -37.8136, 144.9631)
        self.assertAlmostEqual(d, 0.0, places=2)

    def test_haversine_short_distance(self):
        # 1 degree of latitude is ~111 km.
        d = _haversine_meters(-37.0, 144.0, -36.0, 144.0)
        self.assertGreater(d, 110000)
        self.assertLess(d, 112000)
