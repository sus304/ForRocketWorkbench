"""Unit tests for the pure-math helpers in lib/.

These modules (atmosphere model, gravity, coordinate transforms, Vincenty geodesics)
are binary-independent and previously had little or no coverage. The reference values
below are either physical constants (1976 standard atmosphere, WGS84) or were verified
against the implementation for well-known geometric cases (equatorial radius, meridian
arc length, identity rotations).
"""
import os
import sys

import numpy as np
import pytest

from lib.coordinate import (
    DCM_ECEF2NED,
    DCM_ECI2ECEF,
    DCM_NED2BODY_euler,
    DCM_NED2BODY_quat,
    ECEF2LLH,
    LLH2ECEF,
    euler2quat,
    quat2euler,
    quat_normalize,
)
from lib.environment import (
    Wind_NED,
    get_std_press_array,
    gravity,
    magnetic_declination,
    std_atmo,
)

# lib/vincenty.py uses a bare `import wgs84`, so it only resolves with lib/ on sys.path
# (it is not reachable as `lib.vincenty`). Replicate that here so the geodesic solver
# can be exercised. It is otherwise unused by the application code.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.pardir, "lib"))
from vincenty import vdownrange  # noqa: E402


class TestStdAtmo:
    def test_sea_level(self):
        T, P, rho, a = std_atmo(0.0)
        assert T == pytest.approx(288.15)
        assert P == pytest.approx(101325.0)
        assert rho == pytest.approx(1.225, rel=1e-3)
        assert a == pytest.approx(340.3, rel=1e-3)

    def test_pressure_decreases_with_altitude(self):
        assert std_atmo(0.0)[1] > std_atmo(11e3)[1] > std_atmo(50e3)[1]

    def test_above_model_ceiling_clamps_to_top_layer(self):
        # Above 84.852 km the model uses the topmost layer; should not raise.
        T, P, rho, a = std_atmo(120e3)
        assert T == pytest.approx(186.946)
        assert P > 0.0

    def test_accessor_helpers_agree_with_std_atmo(self):
        from lib.environment import (
            get_std_density,
            get_std_press,
            get_std_soundspeed,
            get_std_temp,
        )

        ref = std_atmo(5000.0)
        assert get_std_temp(5000.0) == pytest.approx(ref[0])
        assert get_std_press(5000.0) == pytest.approx(ref[1])
        assert get_std_density(5000.0) == pytest.approx(ref[2])
        assert get_std_soundspeed(5000.0) == pytest.approx(ref[3])

    def test_array_accessor(self):
        alts = np.array([0.0, 1000.0, 2000.0])
        press = get_std_press_array(alts)
        assert press.shape == (3,)
        assert press[0] > press[1] > press[2]


class TestGravity:
    def test_sea_level(self):
        assert gravity(0.0) == pytest.approx(9.80665)

    def test_decreases_with_altitude(self):
        assert gravity(0.0) > gravity(100e3)

    def test_negative_altitude_clamped(self):
        assert gravity(-500.0) == pytest.approx(gravity(0.0))


class TestWindNED:
    def test_north_wind(self):
        # Wind *from* north blows toward south: NED north component is negative.
        w = Wind_NED(10.0, 0.0)
        assert w == pytest.approx([-10.0, 0.0, 0.0])

    def test_east_wind(self):
        # Wind from east blows toward west: NED east component is negative.
        w = Wind_NED(10.0, 90.0)
        assert w[0] == pytest.approx(0.0, abs=1e-9)
        assert w[1] == pytest.approx(-10.0)
        assert w[2] == 0.0


class TestMagneticDeclination:
    def test_reference_point(self):
        # At the model's reference origin (37N, 138E) only the constant term remains.
        assert magnetic_declination(37.0, 138.0) == pytest.approx(7.0 + 57.201 / 60.0)


class TestCoordinateTransforms:
    def test_llh2ecef_equator_prime_meridian(self):
        # Surface point at (0,0) sits on the +X axis at the equatorial radius.
        from lib import wgs84

        assert LLH2ECEF([0.0, 0.0, 0.0]) == pytest.approx([wgs84.a, 0.0, 0.0])

    def test_llh_ecef_roundtrip(self):
        llh = [35.0, 139.0, 1000.0]
        recovered = ECEF2LLH(LLH2ECEF(llh))
        assert recovered[0] == pytest.approx(35.0, abs=1e-6)
        assert recovered[1] == pytest.approx(139.0, abs=1e-6)
        assert recovered[2] == pytest.approx(1000.0, abs=1e-3)

    def test_quat_normalize_unit_norm(self):
        q = quat_normalize(np.array([1.0, 2.0, 3.0, 4.0]))
        assert np.linalg.norm(q) == pytest.approx(1.0)

    def test_euler_quat_dcm_consistency(self):
        az, el, rol = 30.0, 10.0, 5.0
        q = euler2quat(az, el, rol)
        assert np.linalg.norm(q) == pytest.approx(1.0)
        dcm_from_quat = DCM_NED2BODY_quat(q)
        dcm_from_euler = DCM_NED2BODY_euler(
            np.radians(az), np.radians(el), np.radians(rol)
        )
        assert np.allclose(dcm_from_quat, dcm_from_euler, atol=1e-12)

    def test_quat2euler_roundtrip(self):
        az, el, rol = 30.0, 10.0, 5.0
        dcm = DCM_NED2BODY_quat(euler2quat(az, el, rol))
        r_az, r_el, r_rol = quat2euler(dcm)
        assert r_az == pytest.approx(az, abs=1e-9)
        assert r_el == pytest.approx(el, abs=1e-9)
        assert r_rol == pytest.approx(rol, abs=1e-9)

    def test_dcm_orthonormal(self):
        dcm = DCM_NED2BODY_euler(np.radians(40.0), np.radians(-15.0), np.radians(20.0))
        assert np.allclose(dcm @ dcm.T, np.eye(3), atol=1e-12)

    def test_dcm_eci2ecef_identity_at_t0(self):
        assert np.allclose(DCM_ECI2ECEF(0.0), np.eye(3))

    def test_dcm_ecef2ned_orthonormal(self):
        dcm = DCM_ECEF2NED([35.0, 139.0, 0.0])
        assert np.allclose(dcm @ dcm.T, np.eye(3), atol=1e-12)


class TestVincenty:
    def test_identical_points(self):
        assert vdownrange([35.0, 139.0, 0.0], [35.0, 139.0, 0.0]) == (0.0, 0.0)

    def test_meridian_one_degree(self):
        # One degree of latitude along the prime meridian, heading due north.
        dist, az = vdownrange([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        assert dist == pytest.approx(110574.4, rel=1e-5)
        assert az == pytest.approx(0.0, abs=1e-9)

    def test_reverse_azimuth_is_south(self):
        dist, az = vdownrange([1.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        assert dist == pytest.approx(110574.4, rel=1e-5)
        assert az == pytest.approx(180.0)

    def test_oblique_distance(self):
        # Tokyo -> Osaka, verified against the implementation (~404 km).
        dist, az = vdownrange([35.681, 139.767, 0.0], [34.702, 135.495, 0.0])
        assert dist == pytest.approx(403908.2, rel=1e-4)
        assert -180.0 <= az <= 180.0
