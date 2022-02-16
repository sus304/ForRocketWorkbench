import numpy as np

def make_law_wind(height_ref, vel_ref, dir_ref, exp_a):
    '''
    0~20kmのべき風arrayを生成する
    '''
    def _law_method(alt):
        return vel_ref * (alt / height_ref) ** (1 / exp_a)

    alt_max = 20000.0  # 20 km

    base = np.cos(np.arange(0.0, 0.5*np.pi, 0.005))
    alt_array = alt_max * (1 - base)
    vel_array = _law_method(alt_array)
    vel_u_array = -1.0 * vel_array * np.cos(np.radians(dir_ref))
    vel_v_array = -1.0 * vel_array * np.sin(np.radians(dir_ref))

    return alt_array, vel_u_array, vel_v_array

