"""落下分散楕円の数値回帰テスト。

楕円は「共分散楕円」であって確率楕円ではない。半軸は k·√λ で、2次元包含率は
P(k) = 1 - exp(-k²/2)（k=3 で 98.89%）。1次元の 99.73% とは別物なので、規約と
実測包含率の両方をここで固定する。

- 既知共分散に対する半軸・主軸方位が解析解と一致すること
- 描いた楕円の実測包含率が理論包含率と一致すること
- envelope が楕円に外接し、4隅が中心について対称であること
- post_tool と service が同一の楕円を返すこと（測地変換の二重実装を防ぐ）
"""
import numpy as np
import pytest

from lib.coordinate import DCM_ECEF2NED, ECEF2LLH, LLH2ECEF
from post_tool import post_ellipse as pe
from service.results import compute_impact_ellipses

CENTER = (35.0, 139.0)


def _latlon_from_ne(east, north, center=CENTER):
    """NE オフセット [m] → lat/lon [deg]（fit 側の投影の逆変換）。"""
    llh0 = np.array([center[0], center[1], 0.0])
    ecef0, dcm = LLH2ECEF(llh0), DCM_ECEF2NED(llh0)
    out = []
    for e, n in zip(np.asarray(east).ravel(), np.asarray(north).ravel()):
        llh = ECEF2LLH(ecef0 + dcm.T.dot(np.array([n, e, 0.0])))
        out.append((float(llh[0]), float(llh[1])))
    return [p[0] for p in out], [p[1] for p in out]


def _cov_from(sig_major, sig_minor, theta):
    """主軸方向 theta（東から北向き正）の共分散行列を (east, north) 順で作る。"""
    c, s = np.cos(theta), np.sin(theta)
    rot = np.array([[c, -s], [s, c]])
    return rot @ np.diag([sig_major ** 2, sig_minor ** 2]) @ rot.T


def _exact_sample(cov, n_repeat=1):
    """標本共分散が cov に厳密一致する点群（(east, north) 配列）。

    Z = [[1,-1,1,-1],[1,1,-1,-1]]·√3/2 は標本共分散（ddof=1）が単位行列。
    これに cov のコレスキー因子を掛ければ標本共分散は厳密に cov になる。
    """
    z = np.array([[1.0, -1.0, 1.0, -1.0], [1.0, 1.0, -1.0, -1.0]]) * (np.sqrt(3.0) / 2.0)
    z = np.hstack([z] * n_repeat)
    if n_repeat > 1:  # 繰り返しは自由度を変えるので係数を戻す
        z *= np.sqrt((4 * n_repeat - 1) / (4.0 * n_repeat - n_repeat))
    pts = np.linalg.cholesky(cov) @ z
    return pts[0], pts[1]


# --- 解析解との一致 -----------------------------------------------------------

@pytest.mark.parametrize("theta_deg", [0.0, 30.0, 90.0, 135.0, -60.0])
def test_semi_axes_and_azimuth_match_analytic(theta_deg):
    sig_a, sig_b = 4000.0, 1500.0
    theta = np.radians(theta_deg)
    east, north = _exact_sample(_cov_from(sig_a, sig_b, theta))
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(east, north))

    assert fit.sigma_a == pytest.approx(sig_a, rel=1e-3)
    assert fit.sigma_b == pytest.approx(sig_b, rel=1e-3)
    # 方位は 180 deg 周期。北から時計回りの方位角に直して比較する。
    expected_az = np.degrees(np.pi / 2 - theta) % 180.0
    assert (fit.azimuth_deg - expected_az + 90.0) % 180.0 - 90.0 == pytest.approx(0.0, abs=0.05)

    a, b = fit.semi_axes(3.0)
    assert (a, b) == pytest.approx((3.0 * sig_a, 3.0 * sig_b), rel=1e-3)


def test_isotropic_negative_correlation_is_finite():
    """σ_nn == σ_ee かつ負相関は旧実装の主軸角式が 0/0 → nan になっていた縮退。"""
    east, north = _exact_sample(np.array([[1e6, -5e5], [-5e5, 1e6]]))
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(east, north))
    assert np.isfinite(fit.theta) and np.isfinite(fit.sigma_a) and np.isfinite(fit.sigma_b)
    assert np.isfinite(np.array(pe.ellipse_latlon(fit))).all()
    assert fit.azimuth_deg == pytest.approx(135.0, abs=0.05)  # 負相関 → 北西-南東方向


def test_too_few_points_raises():
    with pytest.raises(pe.EllipseError):
        pe.fit_impact_ellipse([35.0, 35.1], [139.0, 139.1])


# --- 包含率 -------------------------------------------------------------------

def test_containment_formula():
    assert pe.containment_2d(1.0) == pytest.approx(39.35, abs=0.01)
    assert pe.containment_2d(2.0) == pytest.approx(86.47, abs=0.01)
    assert pe.containment_2d(3.0) == pytest.approx(98.89, abs=0.01)
    assert pe.k_for_containment(0.9973) == pytest.approx(3.4392, abs=1e-3)
    # k=3 は 1次元 3σ の 99.73% ではない（両者を混同させないためのガード）
    assert pe.containment_2d(3.0) < 99.0
    assert pe.containment_2d(pe.k_for_containment(0.9973)) == pytest.approx(99.73, abs=0.01)


@pytest.mark.parametrize("k", [1.0, 2.0, 3.0, 3.4392])
def test_empirical_containment_matches_theory(k):
    rng = np.random.default_rng(20260903)
    cov = _cov_from(4000.0, 1500.0, np.radians(35.0))
    ne = rng.multivariate_normal([0.0, 0.0], cov, size=40000)
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(ne[:, 0], ne[:, 1]))

    inside = float(np.mean(fit.mahalanobis() <= k) * 100.0)
    assert inside == pytest.approx(pe.containment_2d(k), abs=0.5)

    # マハラノビス判定だけでなく、実際に描く多角形の内側かどうかでも確かめる
    poly = pe.ellipse_ne(fit, k, n_points=720, close=True)
    from matplotlib.path import Path as MplPath
    pts = np.stack([fit.east, fit.north], axis=1)
    assert float(MplPath(poly).contains_points(pts).mean() * 100.0) == pytest.approx(inside, abs=0.2)


def test_diagnostics_flag_non_normal_samples():
    rng = np.random.default_rng(7)
    cov = _cov_from(3000.0, 1200.0, 0.4)
    gauss = rng.multivariate_normal([0.0, 0.0], cov, size=5000)
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(gauss[:, 0], gauss[:, 1]))
    diag = pe.diagnose_fit(fit, 3.0, n_boot=100)
    assert diag["warnings"] == []
    assert diag["containment_empirical"] == pytest.approx(98.89, abs=0.5)
    # ブートストラップ CI は半軸を挟む
    lo, hi = diag["semi_major_ci95"]
    assert lo < 3.0 * fit.sigma_a < hi

    # 対数正規を混ぜた強い歪みは警告になる（失敗モード混在・非対称風の代理）
    skewed = np.stack([rng.lognormal(0.0, 1.0, 5000) * 1000.0, rng.normal(0.0, 1200.0, 5000)], axis=1)
    fit2 = pe.fit_impact_ellipse(*_latlon_from_ne(skewed[:, 0], skewed[:, 1]))
    diag2 = pe.diagnose_fit(fit2, 3.0, n_boot=100)
    assert diag2["warnings"]
    assert any("skew" in w for w in diag2["warnings"])


# --- envelope の幾何 ----------------------------------------------------------

@pytest.mark.parametrize("theta_deg", [0.0, 25.0, 90.0, 160.0])
def test_envelope_circumscribes_the_ellipse(theta_deg):
    east, north = _exact_sample(_cov_from(4000.0, 1500.0, np.radians(theta_deg)))
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(east, north))
    k = 3.0
    a, b = fit.semi_axes(k)
    corners = pe.envelope_ne(fit, k)
    ell = pe.ellipse_ne(fit, k, n_points=720)

    # 主軸系に戻すと ±(a, b) の長方形（＝楕円の外接長方形）になっている
    c, s = np.cos(fit.theta), np.sin(fit.theta)
    to_principal = np.array([[c, s], [-s, c]])
    uv = corners @ to_principal.T
    assert np.allclose(np.abs(uv), [[a, b]] * 4, rtol=1e-9)

    # 楕円は長方形の内側にあり、各辺に接する
    ell_uv = ell @ to_principal.T
    assert np.all(np.abs(ell_uv[:, 0]) <= a * (1 + 1e-9))
    assert np.all(np.abs(ell_uv[:, 1]) <= b * (1 + 1e-9))
    assert np.max(ell_uv[:, 0]) == pytest.approx(a, rel=1e-4)
    assert np.max(ell_uv[:, 1]) == pytest.approx(b, rel=1e-4)

    # 4隅は中心について対称（対角の和が 0）
    assert np.allclose(corners[0] + corners[2], 0.0, atol=1e-6)
    assert np.allclose(corners[1] + corners[3], 0.0, atol=1e-6)

    # 外接長方形は楕円より広く含む: 面積比は 4/π
    assert (4 * a * b) / (np.pi * a * b) == pytest.approx(4.0 / np.pi)


def test_latlon_output_round_trips_through_the_local_frame():
    """KML に出す lat/lon が、同じ局所フレームで NE に戻ること（測地変換の往復整合）。"""
    east, north = _exact_sample(_cov_from(4000.0, 1500.0, 0.7))
    fit = pe.fit_impact_ellipse(*_latlon_from_ne(east, north))
    for latlon, ne in [(pe.envelope_latlon(fit, 3.0), pe.envelope_ne(fit, 3.0)),
                       (pe.ellipse_latlon(fit, 3.0), pe.ellipse_ne(fit, 3.0))]:
        for (lat, lon), (e, n) in zip(latlon, ne):
            assert fit.frame.latlon_to_ne(lat, lon) == pytest.approx((e, n), abs=0.05)


# --- 二重実装の再発防止 -------------------------------------------------------

def test_service_and_post_tool_agree():
    """service 側は球近似ではなく post_ellipse の WGS84 変換を使う（問題3の回帰ガード）。"""
    rng = np.random.default_rng(3)
    ne = rng.multivariate_normal([0.0, 0.0], _cov_from(5000.0, 2000.0, 1.1), size=2000)
    lats, lons = _latlon_from_ne(ne[:, 0], ne[:, 1])

    east, north, mlat, mlon, ne_ell, ll_ell, err = compute_impact_ellipses(lats, lons)
    assert err is None
    fit = pe.fit_impact_ellipse(lats, lons)

    assert (mlat, mlon) == pytest.approx((fit.center_lat, fit.center_lon))
    assert np.allclose(east, fit.east) and np.allclose(north, fit.north)
    assert [k for k, _, _ in ne_ell] == [1.0, 2.0, 3.0]
    for k, _clr, pts in ne_ell:
        assert np.allclose(np.array(pts), pe.ellipse_ne(fit, k, close=True))
    for (k, _clr, ll_pts), (_k2, _c2, ne_pts) in zip(ll_ell, ne_ell):
        assert ll_pts[0] == ll_pts[-1]                       # 閉じている
        assert ll_pts[0] == fit.ne_to_latlon(*ne_pts[0])     # 同じ測地変換
