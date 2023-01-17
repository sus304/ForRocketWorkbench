# Author: Susumu Tanaka
import numpy as np

a = 6378.137e3  # [m]
inv_f = 298.257223563
omega = 7292115e-11  # [rad/s]
GM = 3.986004418e14  # [m3/s2] geocentric gravitational constant
f = 1.0 / inv_f
b = a * (1.0 - f)  # [m] semi-minor axis
e_square = 2.0 * f - f ** 2
e = np.sqrt(e_square)  # 離心率