# Author: Susumu Tanaka
import numpy as np

import wgs84

# Vincenty Method
# Ref. DIRECT AND INVERSE SOLUTIONS OF GEODESICS ON THE ELLIPSOID WITH APPLICATION OF NESTED EQUATIONS T.Vinccnty 
def vdownrange(start_LLH, end_LLH, itr_limit=5000):
    '''
    Input: [lat, lon, alt], [lat, lon, alt] ([deg, m])
    Output: downrange [m], Azimuth start->end [deg]
    '''
    if start_LLH[0] == end_LLH[0] and start_LLH[1] == end_LLH[1]:
        return 0.0, 0.0

    lat1 = np.deg2rad(start_LLH[0])
    lon1 = np.deg2rad(start_LLH[1])

    lat2 = np.deg2rad(end_LLH[0])
    lon2 = np.deg2rad(end_LLH[1])

    U1 = np.arctan((1.0 - wgs84.f) * np.tan(lat1))
    U2 = np.arctan((1.0 - wgs84.f) * np.tan(lat2))

    diffLon = lon2 - lon1

    lamda = diffLon
    for i in range(itr_limit):
        sin_sigma = (np.cos(U2) * np.sin(lamda)) ** 2 + (np.cos(U1) * np.sin(U2) - np.sin(U1) * np.cos(U2) * np.cos(lamda)) ** 2
        sin_sigma = np.sqrt(sin_sigma)
        cos_sigma = np.sin(U1) * np.sin(U2) + np.cos(U1) * np.cos(U2) * np.cos(lamda)
        sigma = np.arctan2(sin_sigma, cos_sigma)
        
        sin_alpha = np.cos(U1) * np.cos(U2) * np.sin(lamda) / sin_sigma
        cos_alpha = np.sqrt(1.0 - sin_alpha ** 2)

        cos_2sigma_m = cos_sigma - 2.0 * np.sin(U1) * np.sin(U2) / (cos_alpha ** 2)
        
        coeff = wgs84.f / 16.0 * cos_alpha ** 2 * (4.0 + wgs84.f * (4.0 - 3.0 * cos_alpha ** 2))
        lamda_itr = lamda
        lamda = diffLon + (1.0 - coeff) * wgs84.f * sin_alpha * (sigma + coeff * sin_sigma * (cos_2sigma_m + coeff * cos_sigma * (-1.0 + 2.0 * cos_2sigma_m)))
         
        if np.abs(lamda - lamda_itr) < 1e-12:
            break
        else:
            pass
            # TODO: 収束しなかった時の処理
    
    u_squr = cos_alpha ** 2 * (wgs84.a ** 2 - wgs84.b ** 2) / wgs84.b ** 2
    A = 1.0 + u_squr / 16384.0 * (4096.0 + u_squr * (-768.0 + u_squr * (320.0 - 175.0 * u_squr)))
    B = u_squr / 1024.0 * (256.0 + u_squr * (-128.0 + u_squr * (74.0 - 47.0 * u_squr)))
    delta_sigma = B * sin_sigma * (cos_2sigma_m + 0.25 * B *(cos_sigma * (-1.0 + 2.0 * cos_2sigma_m ** 2) - \
                        (1.0 / 6.0) * B * cos_2sigma_m * (-3.0 + 4.0 * sin_sigma ** 2) * (-3.0 + 4.0 * cos_2sigma_m ** 2)))

    dist = wgs84.b * A * (sigma - delta_sigma)
    alpha1 = np.arctan2(np.cos(U2) * np.sin(lamda), (np.cos(U1) * np.sin(U2) - np.sin(U1) * np.cos(U2) * np.cos(lamda)))
    alpha2 = np.arctan2(np.cos(U1) * np.sin(lamda), (-np.sin(U1) * np.cos(U2) + np.cos(U1) * np.sin(U2) * np.cos(lamda)))

    return dist, np.rad2deg(alpha1)#, np.rad2deg(alpha2)



