import numpy as np
import simplekml

def dump_trajectory_kml(df_all, file_prefix):
    kml = simplekml.Kml(open=1)

    lat_array = np.array(df_all["Latitude [deg]"])
    lon_array = np.array(df_all["Longitude [deg]"])
    alt_array = np.array(df_all["Altitude [m]"])

    idx = np.arange(0, len(alt_array), 10)  # そのままプロットすると点が多すぎて重いので間引く
    log_lon_lat_alt = np.column_stack([lon_array[idx], lat_array[idx], alt_array[idx]]).tolist()

    line = kml.newlinestring()
    line.style.linestyle.width = 5
    line.style.linestyle.color = simplekml.Color.red
    line.extrude = 1
    line.altitudemode = simplekml.AltitudeMode.absolute
    line.coords = log_lon_lat_alt
    line.style.linestyle.colormode = simplekml.ColorMode.random
    kml.save(file_prefix + '_trajectory.kml')


def dump_iip_kml(lat_array, lon_array, file_prefix):
    kml = simplekml.Kml(open=1)
    lat_array = np.asarray(lat_array)
    lon_array = np.asarray(lon_array)
    if len(lat_array) == 0:
        kml.save(file_prefix + '_iip.kml')
        return

    idx = np.arange(0, len(lat_array), 10)  # 間引き
    iip_lon_lat = np.column_stack([lon_array[idx], lat_array[idx]]).tolist()

    line = kml.newlinestring()
    line.style.linestyle.width = 4
    line.style.linestyle.color = simplekml.Color.blue
    line.coords = iip_lon_lat
    kml.save(file_prefix + '_iip.kml')


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


def dump_montecarlo_points_kml(impact_points_LatLon, case_numbers, file_prefix):
    kml = simplekml.Kml()
    for i in range(len(impact_points_LatLon)):
        kml_point = kml.newpoint()
        p = [[impact_points_LatLon[i][1], impact_points_LatLon[i][0]]]
        kml_point.coords = p
        kml_point.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
        exdata = simplekml.ExtendedData()
        exdata.newdata(name='Case', value=case_numbers[i])
        exdata.newdata(name='Lat', value=impact_points_LatLon[i][0])
        exdata.newdata(name='Lon', value=impact_points_LatLon[i][1])
        kml_point.extendeddata = exdata
    kml.save(file_prefix + '_impact_points.kml')

def dump_montecarlo_envelop_kml(envelop_corner_LatLon, file_prefix, name=None, description=None):
    """Write a closed polyline KML for an impact-dispersion boundary.

    `name`/`description` carry the containment convention into the file itself: opened in
    Google Earth the file name only says "3sigma", which reads as the 1-D 99.73% and is not
    what either the ellipse or its envelope contains (post_ellipse module docstring).
    """
    kml = simplekml.Kml()
    linestring = kml.newlinestring()
    linestring.style.linestyle.color = simplekml.Color.orange
    if name:
        linestring.name = name
        kml.document.name = name
    if description:
        linestring.description = description
        kml.document.description = description
    kml_points = []
    for point in envelop_corner_LatLon:
        p = [point[1], point[0], 0]
        kml_points.append(p)
    kml_points.append(kml_points[0])
    linestring.coords = kml_points
    kml.save(file_prefix + '_impact_3sigma_envelop.kml')



