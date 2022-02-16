import numpy as np
import pandas as pd
import simplekml

def dump_trajectory_kml(df_all, file_prefix):
    kml = simplekml.Kml(open=1)

    lat_array = np.array(df_all["Latitude [deg]"])
    lon_array = np.array(df_all["Longitude [deg]"])
    alt_array = np.array(df_all["Altitude [m]"])

    log_lon_lat_alt = []
    for i in range(len(alt_array)):
        if 0 == i % 10:  # そのままプロットすると点が多すぎて重いので間引く
            log_lon_lat_alt.append([lon_array[i], lat_array[i], alt_array[i]])  # kmlの仕様上Lon,Lat,Heightの並びに変換
    
    line = kml.newlinestring()
    line.style.linestyle.width = 5
    line.style.linestyle.color = simplekml.Color.red
    line.extrude = 1
    line.altitudemode = simplekml.AltitudeMode.absolute
    line.coords = log_lon_lat_alt
    line.style.linestyle.colormode = simplekml.ColorMode.random
    kml.save(file_prefix + '_trajectory.kml')


def dump_area_kml(impact_points_LatLon, file_prefix):
    kml = simplekml.Kml()
    for vel_iter in impact_points_LatLon:
        points = []
        linestring = kml.newlinestring()
        linestring.style.linestyle.color = simplekml.Color.orange
        for i in range(len(vel_iter)):
            lat = vel_iter[i][0]
            lon = vel_iter[i][1]
            points.append([lon, lat, 0.0])
        points.append(points[0])
        linestring.coords = points
    kml.save(file_prefix + '_impact_area.kml')


def dump_dispersion_points_kml(impact_points_LatLon, file_prefix):
    kml = simplekml.Kml()
    for i in range(len(impact_points_LatLon)):
        kml_point = kml.newpoint()
        p = [[impact_points_LatLon[i][1], impact_points_LatLon[i][0]]]
        kml_point.coords = p
        # kml_point.style.iconstyle.icon.href = None
        kml_point.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    kml.save(file_prefix + '_impact_points.kml')


def dump_dispersion_ellipse_kml(ellipse_points_latlon, file_prefix):
    kml = simplekml.Kml()
    linestring = kml.newlinestring()
    linestring.style.linestyle.color = simplekml.Color.orange
    kml_points = []
    for point in ellipse_points_latlon:
        p = [point[1], point[0], 0]
        kml_points.append(p)
    kml_points.append(kml_points[0])
    linestring.coords = kml_points
    kml.save(file_prefix + '_impact_3sigma_ellipse.kml')


