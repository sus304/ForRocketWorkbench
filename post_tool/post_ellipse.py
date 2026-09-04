"""Impact-dispersion ellipse fitting — the single implementation used by both the
post-processing tools and the result service.

Convention (design §5 / review Y7)
----------------------------------
The ellipse is a *covariance* ellipse: its semi-axes are ``k * sqrt(lambda)`` where
``lambda`` are the eigenvalues of the impact-point covariance in the local NE plane.
``k`` is a Mahalanobis radius, NOT a 1-D sigma level, so its 2-D containment is

    P(k) = 1 - exp(-k**2 / 2)

    k = 1.0    -> 39.35 %        k = 3.0    -> 98.89 %
    k = 2.0    -> 86.47 %        k = 3.4392 -> 99.73 %   (= sqrt(chi2.ppf(0.9973, df=2)))

The default stays ``k = 3.0`` and the output file names keep the ``3sigma`` token, so a
"3 sigma ellipse" here contains 98.89 % of a bivariate-normal population — not the 99.73 %
of the 1-D order-statistic "3 sigma" written by :mod:`post_tool.post_summary`. Every label
that names the ellipse must carry both ``k`` and the containment; use :func:`convention_label`.

Geodesy: points are converted LLH -> ECEF -> local NED about the sample mean using the WGS84
ellipsoid (:mod:`lib.coordinate`). No spherical-Earth approximation is used anywhere.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from lib.coordinate import LLH2ECEF, ECEF2LLH, DCM_ECEF2NED

#: Default Mahalanobis radius. Kept at 3.0 for output compatibility (design §5 / Y7).
DEFAULT_K = 3.0

#: Non-normality warning thresholds for the fit diagnostics.
SKEW_WARN = 0.5
EXCESS_KURTOSIS_WARN = 1.0


class EllipseError(ValueError):
    """The impact points do not admit an ellipse fit (too few points, or degenerate)."""


def containment_2d(k: float) -> float:
    """Fraction of a bivariate normal inside the ``k*sqrt(lambda)`` ellipse, in percent."""
    return float(100.0 * (1.0 - np.exp(-0.5 * float(k) ** 2)))


def k_for_containment(p: float) -> float:
    """Mahalanobis radius whose 2-D containment is ``p`` (0-1). ``k_for_containment(0.9973)``
    is 3.4392 — the radius that matches the 1-D 3-sigma probability."""
    return float(np.sqrt(stats.chi2.ppf(p, df=2)))


def convention_label(k: float = DEFAULT_K) -> str:
    """One-line statement of the ellipse convention, for KML/plot/summary labels."""
    return f"k={k:g} (Mahalanobis, semi-axes = k*sqrt(lambda)); 2-D containment {containment_2d(k):.2f}%"


@dataclass
class LocalFrame:
    """Impact points projected onto the local NED tangent plane about their mean (WGS84).

    Shared by the ellipse fit and by callers that only need the scatter (e.g. a plot whose
    ellipse could not be fitted).
    """

    center_lat: float
    center_lon: float
    east: np.ndarray = field(repr=False)      # [m]
    north: np.ndarray = field(repr=False)     # [m]
    ecef_mean: np.ndarray = field(repr=False)
    dcm: np.ndarray = field(repr=False)

    def ne_to_latlon(self, east_m, north_m):
        """Local-frame [m] -> [lat, lon] [deg] on the WGS84 ellipsoid."""
        ecef = self.ecef_mean + self.dcm.T.dot(np.array([north_m, east_m, 0.0]))
        llh = ECEF2LLH(ecef)
        return [float(llh[0]), float(llh[1])]

    def latlon_to_ne(self, lat, lon):
        """[lat, lon] [deg] -> local-frame (east, north) [m]. Inverse of :meth:`ne_to_latlon`
        up to the tangent-plane height the forward map introduces (millimetres at MC scale)."""
        ned = self.dcm.dot(LLH2ECEF(np.array([float(lat), float(lon), 0.0])) - self.ecef_mean)
        return float(ned[1]), float(ned[0])


def project_to_local_ne(lat_list, lon_list) -> LocalFrame:
    """LLH -> local NED about the sample mean, on the WGS84 ellipsoid.

    Non-finite points are dropped. Raises :class:`EllipseError` if nothing usable is left.
    """
    lats = np.asarray(lat_list, dtype=float).ravel()
    lons = np.asarray(lon_list, dtype=float).ravel()
    if lats.shape != lons.shape:
        raise EllipseError("lat/lon must have the same length")
    good = np.isfinite(lats) & np.isfinite(lons)
    lats, lons = lats[good], lons[good]
    if len(lats) == 0:
        raise EllipseError("no finite impact points")

    center = np.array([float(lats.mean()), float(lons.mean()), 0.0])
    ecef_mean = LLH2ECEF(center)
    dcm = DCM_ECEF2NED(center)
    ned = np.array([dcm.dot(LLH2ECEF(np.array([la, lo, 0.0])) - ecef_mean)
                    for la, lo in zip(lats, lons)])
    return LocalFrame(center_lat=center[0], center_lon=center[1],
                      east=ned[:, 1], north=ned[:, 0], ecef_mean=ecef_mean, dcm=dcm)


@dataclass
class EllipseFit:
    """A fitted impact-dispersion ellipse, in *1-sigma* form: scale by ``k`` when drawing.

    ``theta`` is the major-axis direction in the local E-N plane, measured from East toward
    North (counter-clockwise), in radians.
    """

    frame: LocalFrame
    sigma_a: float          # major 1-sigma semi-axis = sqrt(lambda_max) [m]
    sigma_b: float          # minor 1-sigma semi-axis = sqrt(lambda_min) [m]
    theta: float            # [rad] major axis, from East toward North
    n: int

    center_lat = property(lambda self: self.frame.center_lat)
    center_lon = property(lambda self: self.frame.center_lon)
    east = property(lambda self: self.frame.east)
    north = property(lambda self: self.frame.north)

    @property
    def azimuth_deg(self) -> float:
        """Compass azimuth of the major axis [deg], 0 = North, 90 = East, in [0, 180)."""
        return float(np.degrees(np.pi / 2 - self.theta) % 180.0)

    def semi_axes(self, k: float = DEFAULT_K):
        """(major, minor) semi-axes [m] of the k-ellipse."""
        return float(k) * self.sigma_a, float(k) * self.sigma_b

    def mahalanobis(self) -> np.ndarray:
        """Mahalanobis radius of every sample point w.r.t. the fitted ellipse."""
        u, v = self._principal_coords()
        return np.hypot(u / self.sigma_a, v / self.sigma_b)

    def _principal_coords(self):
        """Sample coordinates along the major/minor axes, centred on the fit."""
        de = self.east - self.east.mean()
        dn = self.north - self.north.mean()
        c, s = np.cos(self.theta), np.sin(self.theta)
        return de * c + dn * s, -de * s + dn * c

    def ne_to_latlon(self, east_m, north_m):
        """Local-frame [m] -> [lat, lon] [deg] on the WGS84 ellipsoid."""
        return self.frame.ne_to_latlon(east_m, north_m)


def fit_impact_ellipse(lat_list, lon_list) -> EllipseFit:
    """Fit the impact covariance ellipse. Raises :class:`EllipseError` if it cannot be fitted."""
    frame = project_to_local_ne(lat_list, lon_list)
    if len(frame.east) < 3:
        raise EllipseError(f"need at least 3 finite impact points, got {len(frame.east)}")

    # Principal axes in the (East, North) plane. eigh returns ascending eigenvalues.
    cov = np.cov(np.stack([frame.east, frame.north]))
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals, eigvecs = eigvals[order], eigvecs[:, order]
    sigma_a = float(np.sqrt(max(float(eigvals[0]), 0.0)))
    sigma_b = float(np.sqrt(max(float(eigvals[1]), 0.0)))
    if not np.isfinite(sigma_a) or sigma_a <= 0.0:
        raise EllipseError("impact points are degenerate (zero-variance covariance)")
    major = eigvecs[:, 0]
    theta = float(np.arctan2(major[1], major[0]))  # from East toward North

    return EllipseFit(frame=frame, sigma_a=sigma_a, sigma_b=sigma_b, theta=theta,
                      n=int(len(frame.east)))


def _rotate(u, v, theta):
    """Principal-frame (u, v) -> local-frame (east, north)."""
    c, s = np.cos(theta), np.sin(theta)
    return u * c - v * s, u * s + v * c


def ellipse_ne(fit: EllipseFit, k: float = DEFAULT_K, n_points: int = 72, close: bool = False):
    """The k-ellipse as an (m, 2) array of (east, north) [m]."""
    a, b = fit.semi_axes(k)
    t = np.linspace(0.0, 2.0 * np.pi, n_points, endpoint=False)
    e, n = _rotate(a * np.cos(t), b * np.sin(t), fit.theta)
    pts = np.stack([e, n], axis=1)
    return np.vstack([pts, pts[:1]]) if close else pts


def ellipse_latlon(fit: EllipseFit, k: float = DEFAULT_K, n_points: int = 72):
    """The k-ellipse as a list of [lat, lon] [deg]."""
    return [fit.ne_to_latlon(e, n) for e, n in ellipse_ne(fit, k, n_points)]


def envelope_ne(fit: EllipseFit, k: float = DEFAULT_K):
    """The four corners of the rectangle circumscribing the k-ellipse, as (4, 2) (east, north).

    The rectangle is axis-aligned *in the ellipse's principal frame*, so its sides touch the
    ellipse at the four axis endpoints and its corners are (+-a, +-b) rotated by ``theta``.
    Ordered counter-clockwise in that frame, so the polyline traces the rectangle.
    """
    a, b = fit.semi_axes(k)
    corners = [(a, b), (-a, b), (-a, -b), (a, -b)]
    return np.array([_rotate(u, v, fit.theta) for u, v in corners])


def envelope_latlon(fit: EllipseFit, k: float = DEFAULT_K):
    """The circumscribing rectangle as a list of [lat, lon] [deg]."""
    return [fit.ne_to_latlon(e, n) for e, n in envelope_ne(fit, k)]


def diagnose_fit(fit: EllipseFit, k: float = DEFAULT_K, n_boot: int = 400,
                 seed: int = 0, boot_min_n: int = 200) -> dict:
    """How well does the covariance ellipse actually describe the impact points?

    Returns the empirical containment of the k-ellipse, the skewness / excess kurtosis along
    the principal axes, any threshold warnings, and (when the sample is large enough) a
    bootstrap 95 % CI of the semi-axes. Impact dispersions go non-normal easily — mixed
    failure modes, asymmetric winds — and the ellipse alone cannot show that.
    """
    u, v = fit._principal_coords()
    out = {
        "n": fit.n,
        "k": float(k),
        "containment_theoretical": containment_2d(k),
        "containment_empirical": float(100.0 * np.mean(fit.mahalanobis() <= k)),
        "skew_major": float(stats.skew(u)),
        "skew_minor": float(stats.skew(v)),
        "excess_kurtosis_major": float(stats.kurtosis(u, fisher=True)),
        "excess_kurtosis_minor": float(stats.kurtosis(v, fisher=True)),
        "warnings": [],
    }
    for axis in ("major", "minor"):
        if abs(out[f"skew_{axis}"]) > SKEW_WARN:
            out["warnings"].append(
                f"skewness on the {axis} axis is {out[f'skew_{axis}']:+.2f} "
                f"(|skew| > {SKEW_WARN}); the distribution is asymmetric and the ellipse is "
                f"centred on the mean, not the mode")
        if abs(out[f"excess_kurtosis_{axis}"]) > EXCESS_KURTOSIS_WARN:
            out["warnings"].append(
                f"excess kurtosis on the {axis} axis is {out[f'excess_kurtosis_{axis}']:+.2f} "
                f"(|excess kurtosis| > {EXCESS_KURTOSIS_WARN}); tails are not Gaussian and the "
                f"ellipse under- or over-states the outer contour")
    gap = out["containment_empirical"] - out["containment_theoretical"]
    if abs(gap) > 1.0:
        out["warnings"].append(
            f"empirical containment {out['containment_empirical']:.2f}% differs from the "
            f"theoretical {out['containment_theoretical']:.2f}% by {gap:+.2f} points; the "
            f"Gaussian assumption behind the ellipse does not hold well for this sample")

    if fit.n >= boot_min_n:
        rng = np.random.default_rng(seed)
        pts = np.stack([fit.east, fit.north], axis=1)
        axes = np.empty((n_boot, 2))
        for i in range(n_boot):
            sample = pts[rng.integers(0, fit.n, fit.n)]
            ev = np.linalg.eigvalsh(np.cov(sample.T))
            axes[i] = float(k) * np.sqrt(np.maximum(ev[::-1], 0.0))
        lo, hi = np.percentile(axes, [2.5, 97.5], axis=0)
        out["semi_major_ci95"] = (float(lo[0]), float(hi[0]))
        out["semi_minor_ci95"] = (float(lo[1]), float(hi[1]))
    return out


def write_ellipse_summary(fit: EllipseFit, file_prefix: str, k: float = DEFAULT_K) -> dict:
    """Write ``{prefix}_ellipse_summary.txt`` — the ellipse geometry plus its fit diagnostics.

    Separate from ``{prefix}_summary.txt`` on purpose: that one only exists for >= 1000 cases
    (it reports empirical 99.73 % order statistics), while the ellipse is fitted from 3 points
    up. The ``*_summary.txt`` name still makes the result service pick it up automatically.
    """
    d = diagnose_fit(fit, k)
    a, b = fit.semi_axes(k)
    path = file_prefix + '_ellipse_summary.txt'
    lines = [
        f'Ellipse Convention,{convention_label(k)}\n',
        f'Ellipse Cases,{fit.n}\n',
        f'Ellipse Semi-major,{a:.3f}[m]\n',
        f'Ellipse Semi-minor,{b:.3f}[m]\n',
        f'Ellipse Major-axis Azimuth,{fit.azimuth_deg:.3f}[deg]\n',
        f'Ellipse Center Lat,{fit.center_lat:.6f}[deg]\n',
        f'Ellipse Center Lon,{fit.center_lon:.6f}[deg]\n',
        f'Ellipse Containment Theoretical,{d["containment_theoretical"]:.2f}[%]\n',
        f'Ellipse Containment Empirical,{d["containment_empirical"]:.2f}[%]\n',
        f'Ellipse Skewness Major,{d["skew_major"]:.3f}[-]\n',
        f'Ellipse Skewness Minor,{d["skew_minor"]:.3f}[-]\n',
        f'Ellipse Excess Kurtosis Major,{d["excess_kurtosis_major"]:.3f}[-]\n',
        f'Ellipse Excess Kurtosis Minor,{d["excess_kurtosis_minor"]:.3f}[-]\n',
    ]
    if 'semi_major_ci95' in d:
        lines += [
            f'Ellipse Semi-major CI95,{d["semi_major_ci95"][0]:.3f} - {d["semi_major_ci95"][1]:.3f}[m]\n',
            f'Ellipse Semi-minor CI95,{d["semi_minor_ci95"][0]:.3f} - {d["semi_minor_ci95"][1]:.3f}[m]\n',
        ]
    for i, w in enumerate(d['warnings'], 1):
        lines.append(f'Ellipse Fit Warning {i},{w}\n')
    with open(path, mode='w') as f:
        f.writelines(lines)
    d['path'] = path
    return d
