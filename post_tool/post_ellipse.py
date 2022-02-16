import numpy as np
import pandas as pd
from scipy import stats

def get_ellipse_points(points_latlon):
    lat_list = []
    lon_list = []
    for i in range(len(points_latlon)):
        lat_list.append(points_latlon[i][0])
        lon_list.append(points_latlon[i][1])

    df = pd.DataFrame()
    df['lat'] = np.array(lat_list)
    df['lon'] = np.array(lon_list)

    mean_lat = df['lat'].mean()
    mean_lon = df['lon'].mean()
    mean_latlon = np.array(df.mean())

    cov_matrix = df.cov()
    cov_latlon = cov_matrix['lat']['lon']
    var_lat = cov_matrix['lat']['lat']
    var_lon = cov_matrix['lon']['lon']
    std_lat = np.sqrt(var_lat)
    std_lon = np.sqrt(var_lon)

    corr = cov_latlon / (std_lat * std_lon)

    ellipse_3sigma_points_latlon = []
    p = stats.norm.cdf(3) - stats.norm.cdf(-3)
    for phi_deg in np.arange(0, 360, 1):
        phi = np.deg2rad(phi_deg)
        r = np.sqrt((-2.0 * (1.0 - corr**2) * np.log(1.0 - p)) / (1.0 - 2.0 * corr * np.sin(phi) * np.cos(phi)))
        u = mean_lat + std_lat * r * np.cos(phi)
        v = mean_lon + std_lon * r * np.sin(phi)
        ellipse_3sigma_points_latlon.append([u, v])

    lamda, vecs = np.linalg.eigh(cov_matrix)
    c = np.sqrt(stats.chi2.ppf(p, 2))
    w, h = 2 * c * np.sqrt(lamda)

    return ellipse_3sigma_points_latlon


if __name__ == '__main__':
    latlons = [[25.7,140], [29.2,141], [32,142], [33,143], [43.2,144]]
    get_ellipse_points(latlons)



