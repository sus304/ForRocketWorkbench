import numpy as np
import pandas as pd
from scipy import stats

from lib.coordinate import LLH2ECEF, ECEF2LLH, DCM_ECEF2NED

# class www:
#     def __init__(self):
#         self.a = 6378.137e3  # [m]
#         self.inv_f = 298.257223563
#         self.omega = 7292115e-11  # [rad/s]
#         self.GM = 3.986004418e14  # [m3/s2] geocentric gravitational constant
#         self.f = 1.0 / self.inv_f
#         self.b = self.a * (1.0 - self.f)  # [m] semi-minor axis
#         self.e_square = 2.0 * self.f - self.f ** 2
#         self.e = np.sqrt(self.e_square)  # 離心率
# wgs84 = www()
# def ECEF2LLH(pos_ECEF):
#     x = pos_ECEF[0]
#     y = pos_ECEF[1]
#     z = pos_ECEF[2]

#     p = np.sqrt(x ** 2 + y ** 2)
#     theta = np.arctan2(z * wgs84.a, p * wgs84.b)
#     e_dash_square = (wgs84.a ** 2 - wgs84.b ** 2) / (wgs84.b ** 2)
#     lat = np.arctan2(z + e_dash_square * wgs84.b * (np.sin(theta) ** 3), p - wgs84.e_square * wgs84.a * (np.cos(theta) ** 3))
#     lon = np.arctan2(y, x)
#     N = wgs84.a / np.sqrt(1.0 - wgs84.e_square * np.sin(lat) ** 2)
#     height = p / np.cos(lat) - N
#     return np.array([np.rad2deg(lat), np.rad2deg(lon), height])

# def LLH2ECEF(pos_LLH):
#     lat = np.deg2rad(pos_LLH[0])
#     lon = np.deg2rad(pos_LLH[1])
#     height = pos_LLH[2]

#     N = wgs84.a / np.sqrt(1.0 - wgs84.e_square * np.sin(lat) ** 2)
#     x = (N + height) * np.cos(lat) * np.cos(lon)
#     y = (N + height) * np.cos(lat) * np.sin(lon)
#     z = (N * (1 - wgs84.e_square) + height) * np.sin(lat)
#     return np.array([x, y, z])

# def DCM_ECEF2NED(pos_LLH):
#     '''
#     Input: [deg], [deg], [m]
#     '''
#     # from MATLAB
#     lat = np.deg2rad(pos_LLH[0])
#     lon = np.deg2rad(pos_LLH[1])
#     DCM_0 = [-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)]
#     DCM_1 = [-np.sin(lon), np.cos(lon), 0]
#     DCM_2 = [-np.cos(lat) * np.cos(lon), -np.cos(lat) * np.sin(lon), -np.sin(lat)]
#     DCM_ECEF2NED = np.array([DCM_0, DCM_1, DCM_2])
#     return DCM_ECEF2NED

def get_ellipse_points(points_latlon):
    # Step.1 LLH to ECEF
    pos_ecef_list = []
    for i in range(len(points_latlon)):
        llh = np.array([points_latlon[i][0], points_latlon[i][1], 0.0])
        ecef = LLH2ECEF(llh)
        pos_ecef_list.append(ecef)

    # Step.2 ECEF to NED. center point is mean latlon
    lat_mean = 0.0
    lon_mean = 0.0
    for i in range(len(points_latlon)):
        lat_mean += points_latlon[i][0]
        lon_mean += points_latlon[i][1]
    lat_mean /= len(points_latlon)
    lon_mean /= len(points_latlon)
    ecef_mean = LLH2ECEF(np.array([lat_mean, lon_mean, 0.0]))
    dcm = DCM_ECEF2NED(np.array([lat_mean, lon_mean, 0.0]))
    pos_ned_list = []
    n_array = []
    e_array = []
    for i in range(len(pos_ecef_list)):
        ned = dcm.dot(pos_ecef_list[i] - ecef_mean)
        pos_ned_list.append(ned)
        n_array.append(ned[0])
        e_array.append(ned[1])

    # Step.3 3-sigma Ellipse
    n_array = np.array(n_array)
    e_array = np.array(e_array)
    cov_mat = np.cov([n_array, e_array])
    var_n = cov_mat[0][0]
    var_e = cov_mat[1][1]
    var_ne = cov_mat[0][1]
    w = -var_n - var_e
    eigenvalue_a = (-w + np.sqrt(w * w - 4.0 * (var_n * var_e - (var_ne * var_ne)))) / 2.0
    eigenvalue_b = (-w - np.sqrt(w * w - 4.0 * (var_n * var_e - (var_ne * var_ne)))) / 2.0
    ell_a = 3.0 * np.sqrt(eigenvalue_a)
    ell_b = 3.0 * np.sqrt(eigenvalue_b)
    ell_theta_a = np.arctan((var_e - eigenvalue_a - var_ne) / (var_n - eigenvalue_a - var_ne))
    ell_theta_b = ell_theta_a + np.pi / 2

    # Step.4 Envelope
    def zero_angle_contact_point(d_theta):
        xm = np.sqrt(ell_a**4 * np.tan(d_theta)**2 / (ell_a**2 * np.tan(d_theta)**2 + ell_b**2))
        ym = np.sqrt(ell_b**4 / (ell_a**2 * np.tan(d_theta)**2 + ell_b**2))
        return xm, ym

    delta_theta = ell_theta_a - ell_theta_a
    xm1, ym1 = zero_angle_contact_point(delta_theta)
    if 0 < delta_theta <= np.pi:
        xm1 *= -1.0
    if -np.pi/2 <= delta_theta <= np.pi/2:
        pass
    else:
        ym1 *= -1.0

    delta_theta = ell_theta_b - ell_theta_a
    xm2, ym2 = zero_angle_contact_point(delta_theta)
    if 0 < delta_theta <= np.pi:
        xm2 *= -1.0
    if -np.pi/2 <= delta_theta <= np.pi/2:
        pass
    else:
        ym2 *= -1.0

    delta_theta = ell_theta_a - ell_theta_a
    xm3, ym3 = zero_angle_contact_point(delta_theta)
    if 0 < delta_theta < np.pi:
        pass
    else:
        xm3 *= -1.0
    if -np.pi/2 < delta_theta <= np.pi/2:
        ym3 *= -1.0

    delta_theta = ell_theta_b - ell_theta_a
    xm4, ym4 = zero_angle_contact_point(delta_theta)
    if 0 < delta_theta <= np.pi:
        pass
    else:
        xm4 *= -1.0
    if -np.pi/2 <= delta_theta <= np.pi/2:
        ym4 *= -1.0

    xm1_dash = xm1 * np.cos(ell_theta_a) - ym1 * np.sin(ell_theta_a)
    ym1_dash = xm1 * np.sin(ell_theta_a) + ym1 * np.cos(ell_theta_a)
    xm2_dash = xm2 * np.cos(ell_theta_a) - ym2 * np.sin(ell_theta_a)
    ym2_dash = xm2 * np.sin(ell_theta_a) + ym2 * np.cos(ell_theta_a)
    xm3_dash = xm3 * np.cos(ell_theta_a) - ym3 * np.sin(ell_theta_a)
    ym3_dash = xm3 * np.sin(ell_theta_a) + ym3 * np.cos(ell_theta_a)
    xm4_dash = xm4 * np.cos(ell_theta_a) - ym4 * np.sin(ell_theta_a)
    ym4_dash = xm4 * np.sin(ell_theta_a) + ym4 * np.cos(ell_theta_a)

    def corner_point(alpha1, beta1, alpha2, beta2):
        xk = (beta2 - beta1) / (alpha1 - alpha2)
        yk = (alpha1 * beta2 - alpha2 * beta1) / (alpha1 - alpha2)
        return xk, yk
    alpha1 = np.tan(ell_theta_a)
    beta1 = ym1_dash - xm1_dash * np.tan(ell_theta_a)
    alpha2 = np.tan(ell_theta_b)
    beta2 = ym2_dash - xm2_dash * np.tan(ell_theta_b)
    alpha3 = np.tan(ell_theta_a)
    beta3 = ym3_dash - xm3_dash * np.tan(ell_theta_a)
    alpha4 = np.tan(ell_theta_b)
    beta4 = ym4_dash - xm4_dash * np.tan(ell_theta_b)

    xk1, yk1 = corner_point(alpha1, beta1, alpha2, beta2)
    xk2, yk2 = corner_point(alpha2, beta2, alpha3, beta3)
    xk3, yk3 = corner_point(alpha3, beta3, alpha4, beta4)
    xk4, yk4 = corner_point(alpha4, beta4, alpha1, beta1)

    # Step.5 NED to LLH
    ecef1 = ecef_mean + dcm.transpose().dot(np.array([yk1, xk1, 0]))
    ecef2 = ecef_mean + dcm.transpose().dot(np.array([yk2, xk2, 0]))
    ecef3 = ecef_mean + dcm.transpose().dot(np.array([yk3, xk3, 0]))
    ecef4 = ecef_mean + dcm.transpose().dot(np.array([yk4, xk4, 0]))

    llh1 = ECEF2LLH(ecef1)
    llh2 = ECEF2LLH(ecef2)
    llh3 = ECEF2LLH(ecef3)
    llh4 = ECEF2LLH(ecef4)

    # Step.Ex ellipse output
    theta_array = np.deg2rad(np.arange(0, 360.0, 5.0))
    e1 = ell_a * np.cos(theta_array)
    n1 = ell_b * np.sin(theta_array)
    ell_e_array = e1 * np.cos(ell_theta_a) - n1 * np.sin(ell_theta_a)
    ell_n_array = e1 * np.sin(ell_theta_a) + n1 * np.cos(ell_theta_a)
    ell_llh_list = []
    for i in range(len(theta_array)):
        ecef = ecef_mean + dcm.transpose().dot(np.array([ell_n_array[i], ell_e_array[i], 0]))
        ell_llh_list.append(ECEF2LLH(ecef))


    return [llh1, llh2, llh3, llh4], ell_llh_list



if __name__ == '__main__':
    latlons = [[32.7,142], [32.2,141], [32,142], [33,143], [33.2,142.5]]
    get_ellipse_points(latlons)



