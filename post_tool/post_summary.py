import numpy as np
import pandas as pd

# Target altitude for apogee "reach probability" statistics (Karman line, 100 km).
REACH_ALTITUDE_THRESHOLD_M = 100000.0

def post_summary(df_all, file_prefix):
    vel_b_x_log = df_all["Vx-body [m/s]"]
    vel_b_y_log = df_all["Vy-body [m/s]"]
    vel_b_z_log = df_all["Vz-body [m/s]"]
    vel_norm_log = np.sqrt(vel_b_x_log ** 2 + vel_b_y_log ** 2 + vel_b_z_log ** 2)

    # Launch Clear
    fz_gravity_log = df_all["Fz-gravity [N]"]
    index_launch_clear = np.argmax(np.abs(fz_gravity_log) >= 0.1)
    time_launch_clear = df_all["Time [s]"][index_launch_clear]
    acc_launch_clear = df_all["Gccx-body [G]"][index_launch_clear]
    vel_launch_clear = vel_norm_log[index_launch_clear]
    aoa_launch_clear = df_all["AoA [deg]"][index_launch_clear]
    aos_launch_clear = df_all["AoS [deg]"][index_launch_clear]

    # Apogee
    index_apogee = np.argmax(df_all["Altitude [m]"])
    time_apogee = df_all["Time [s]"][index_apogee]
    altitude_apogee = df_all["Altitude [m]"][index_apogee]
    downrange_apogee = df_all["Downrange [m]"][index_apogee]
    vel_apogee = vel_norm_log[index_apogee]
    pos_apogee = [float(df_all["Latitude [deg]"][index_apogee]), float(df_all["Longitude [deg]"][index_apogee])]

    # MaxQ
    index_maxq = np.argmax(df_all["DynamicPressure [kPa]"][:index_apogee])
    time_maxq = df_all["Time [s]"][index_maxq]
    altitude_maxq = df_all["Altitude [m]"][index_maxq]
    vel_maxq = vel_norm_log[index_maxq]
    mach_maxq = df_all["MachNumber [-]"][index_maxq]
    dynamics_pressure_maxq = df_all["DynamicPressure [kPa]"][index_maxq]

    # Max Vel
    index_maxvel = np.argmax(vel_norm_log[:index_apogee])
    time_maxvel = df_all["Time [s]"][index_maxvel]
    altitude_maxvel = df_all["Altitude [m]"][index_maxvel]
    vel_maxvel = vel_norm_log[index_maxvel]
    mach_maxvel = df_all["MachNumber [-]"][index_maxvel]
    dynamics_pressure_maxvel = df_all["DynamicPressure [kPa]"][index_maxvel]

    # Max Mach
    index_maxmach = np.argmax(df_all["MachNumber [-]"][:index_apogee])
    time_maxmach = df_all["Time [s]"][index_maxmach]
    altitude_maxmach = df_all["Altitude [m]"][index_maxmach]
    vel_maxmach = vel_norm_log[index_maxmach]
    mach_maxmach = df_all["MachNumber [-]"][index_maxmach]
    dynamics_pressure_maxmach = df_all["DynamicPressure [kPa]"][index_maxmach]

    # landing
    time_landing = np.array(df_all["Time [s]"])[-1]
    downrange_landing = np.array(df_all["Downrange [m]"])[-1]
    pos_landing = [float(np.array(df_all["Latitude [deg]"])[-1]), float(np.array(df_all["Longitude [deg]"])[-1])]

    # Spin stability / roll-pitch resonance diagnostics
    total_aoa_launch_clear = float(df_all["TotalAoA [deg]"][index_launch_clear])
    peak_total_aoa = float(np.max(df_all["TotalAoA [deg]"][:index_apogee]))

    spin_rate_log = df_all["AngleVelx [deg/s]"]
    peak_spin_rate = float(np.max(np.abs(spin_rate_log[:index_apogee])))
    burning_log = np.array(df_all["Burning [0/1]"])
    burnout_indices = np.where(burning_log == 1)[0]
    spin_rate_burnout = float(spin_rate_log.iloc[int(burnout_indices[-1])]) if len(burnout_indices) > 0 else float('nan')

    min_sg = float(np.min(df_all["GyroStabilityFactor Sg [-]"][:index_apogee]))
    min_resonance_ratio = float(np.min(df_all["ResonanceRatio [-]"][:index_apogee]))
    max_trim_aoa = float(np.max(df_all["TrimAoA [deg]"][:index_apogee]))
    max_lateral_aero_load = float(np.max(df_all["LateralAeroLoad [N]"][:index_apogee]))

    txt = open(file_prefix + '_summary.txt', mode='w')
    txt.writelines(['Launcher Clear X+,', str(round(time_launch_clear, 3)), '[s]\n'])
    txt.writelines(['Launcher Clear Acceleration,', str(round(acc_launch_clear, 3)), '[G]\n'])
    txt.writelines(['Launcher Clear Velocity,', str(round(vel_launch_clear, 3)), '[m/s]\n'])
    txt.writelines(['Launcher Clear AoA,', str(round(aoa_launch_clear, 3)), '[deg]\n'])
    txt.writelines(['Launcher Clear AoS,', str(round(aos_launch_clear, 3)), '[deg]\n'])
    txt.writelines(['Launcher Clear Total AoA,', str(round(total_aoa_launch_clear, 3)), '[deg]\n'])
    txt.writelines(['Max Q X+,', str(round(time_maxq, 3)), '[s]\n'])
    txt.writelines(['Max Q Altitude,', str(round(altitude_maxq, 3)), '[m]\n'])
    txt.writelines(['Max Q Velocity,', str(round(vel_maxq, 3)), '[m/s]\n'])
    txt.writelines(['Max Q MachNumber,', str(round(mach_maxq, 3)), '[-]\n'])
    txt.writelines(['Max Q Dynamic Pressure,', str(round(dynamics_pressure_maxq, 3)), '[kPa]\n'])
    txt.writelines(['Max Speed X+,', str(round(time_maxvel, 3)), '[s]\n'])
    txt.writelines(['Max Speed Altitude,', str(round(altitude_maxvel, 3)), '[m]\n'])
    txt.writelines(['Max Speed Velocity,', str(round(vel_maxvel, 3)), '[m/s]\n'])
    txt.writelines(['Max Speed MachNumber,', str(round(mach_maxvel, 3)), '[-]\n'])
    txt.writelines(['Max Speed Dynamic Pressure,', str(round(dynamics_pressure_maxvel, 3)), '[kPa]\n'])
    txt.writelines(['Max Mach Number X+,', str(round(time_maxmach, 3)), '[s]\n'])
    txt.writelines(['Max Mach Number Altitude,', str(round(altitude_maxmach, 3)), '[m]\n'])
    txt.writelines(['Max Mach Velocity,', str(round(vel_maxmach, 3)), '[m/s]\n'])
    txt.writelines(['Max Mach Number,', str(round(mach_maxmach, 3)), '[-]\n'])
    txt.writelines(['Max Mach Dynamic Pressure,', str(round(dynamics_pressure_maxmach, 3)), '[kPa]\n'])
    txt.writelines(['Apogee X+,', str(round(time_apogee, 3)), '[s]\n'])
    txt.writelines(['Apogee Altitude,', str(round(altitude_apogee, 3)), '[m]\n'])
    txt.writelines(['Apogee Downrange,', str(round(downrange_apogee, 3)), '[m]\n'])
    txt.writelines(['Apogee Air Velocity,', str(round(vel_apogee, 3)), '[m/s]\n'])
    txt.writelines(['Apogee Point,', str(pos_apogee), '\n'])
    txt.writelines(['Landing X+,', str(round(time_landing, 3)), '[s]\n'])
    txt.writelines(['Landing Downrange,', str(round(downrange_landing, 3)), '[m]\n'])
    txt.writelines(['Landing Point,', str(pos_landing), '\n'])
    txt.writelines(['Peak Total AoA,', str(round(peak_total_aoa, 3)), '[deg]\n'])
    txt.writelines(['Peak Spin Rate,', str(round(peak_spin_rate, 3)), '[deg/s]\n'])
    txt.writelines(['Spin Rate at Burnout,', str(round(spin_rate_burnout, 3) if not np.isnan(spin_rate_burnout) else 'nan'), '[deg/s]\n'])
    txt.writelines(['Min GyroStabilityFactor Sg,', str(round(min_sg, 4)), '[-]\n'])
    txt.writelines(['Min ResonanceRatio,', str(round(min_resonance_ratio, 4)), '[-]\n'])
    txt.writelines(['Max TrimAoA,', str(round(max_trim_aoa, 3)), '[deg]\n'])
    txt.writelines(['Max LateralAeroLoad,', str(round(max_lateral_aero_load, 3)), '[N]\n'])
    txt.close()


    df = pd.DataFrame({'lat': [pos_landing[0]],
                        'lon': [pos_landing[1]]},
    )
    df.to_csv(file_prefix + '_landing_point.csv', index=False)

    return txt, pos_landing

def post_summary_for_montecarlo(df_all):
    vel_b_x_log = df_all["Vx-body [m/s]"]
    vel_b_y_log = df_all["Vy-body [m/s]"]
    vel_b_z_log = df_all["Vz-body [m/s]"]
    vel_norm_log = np.sqrt(vel_b_x_log ** 2 + vel_b_y_log ** 2 + vel_b_z_log ** 2)

    index_apogee = np.argmax(df_all["Altitude [m]"])
    time_apogee = df_all["Time [s]"][index_apogee]
    altitude_apogee = df_all["Altitude [m]"][index_apogee]
    vel_apogee = vel_norm_log[index_apogee]

    index_maxq = np.argmax(df_all["DynamicPressure [kPa]"][:index_apogee])
    dynamic_pressure_maxq = df_all["DynamicPressure [kPa]"][index_maxq]

    index_maxmach = np.argmax(df_all["MachNumber [-]"][:index_apogee])
    mach_maxmach = df_all["MachNumber [-]"][index_maxmach]

    downrange_landing = np.array(df_all["Downrange [m]"])[-1]
    pos_landing = [float(np.array(df_all["Latitude [deg]"])[-1]), float(np.array(df_all["Longitude [deg]"])[-1])]

    # Launch clear: first step where gravity force becomes significant
    fz_gravity_log = df_all["Fz-gravity [N]"]
    index_launch_clear = int(np.argmax(np.abs(fz_gravity_log) >= 0.1))
    aoa_launch_clear = float(df_all["TotalAoA [deg]"].iloc[index_launch_clear])

    # Ascent + high-q mask: exclude the q≈0 region just after balloon release
    # and near apogee, where AoA / resonance diagnostics are degenerate.
    Q_FLOOR_PA = 500.0
    q_pa = df_all["DynamicPressure [kPa]"].to_numpy() * 1000.0
    idx = np.arange(len(df_all))
    ascent_hq = (idx < index_apogee) & (q_pa > Q_FLOOR_PA)
    if not ascent_hq.any():
        ascent_hq = (idx < index_apogee)          # fallback

    # Peak total AoA during ascent (now directly available from ForRocket)
    peak_total_aoa = float(np.max(df_all["TotalAoA [deg]"].to_numpy()[ascent_hq]))

    # Spin rate (body x-axis roll rate) — no q floor: we want the true peak spin for IMU range
    spin_rate_log = df_all["AngleVelx [deg/s]"]
    peak_spin_rate = float(np.max(np.abs(spin_rate_log[:index_apogee])))

    # Spin rate at burnout: last timestep where Burning == 1
    burning_log = np.array(df_all["Burning [0/1]"])
    burnout_indices = np.where(burning_log == 1)[0]
    if len(burnout_indices) > 0:
        index_burnout = int(burnout_indices[-1])
        spin_rate_burnout = float(spin_rate_log.iloc[index_burnout])
    else:
        spin_rate_burnout = float('nan')

    # Roll-pitch resonance diagnostics
    sg_log = df_all["GyroStabilityFactor Sg [-]"]
    min_sg = float(np.min(sg_log[:index_apogee]))

    min_resonance_ratio = float(np.min(df_all["ResonanceRatio [-]"].to_numpy()[ascent_hq]))

    # TrimAoA is a forced-response amplitude (M_asym / (k_alpha * amp_resp)) that diverges
    # near roll-pitch resonance, where the effective restoring stiffness k_alpha*amp_resp -> 0.
    # The q floor alone can't fix this (resonance is crossed at high q too), so clamp each
    # sample to the linear-aero validity ceiling before taking the max. LateralAeroLoad below
    # is built from the actual simulated AoA and stays the bounded structural-load metric.
    TRIM_AOA_CAP_DEG = 15.0
    max_trim_aoa = float(np.minimum(df_all["TrimAoA [deg]"].to_numpy()[ascent_hq], TRIM_AOA_CAP_DEG).max())

    max_lateral_aero_load = float(np.max(df_all["LateralAeroLoad [N]"].to_numpy()[ascent_hq]))

    return (dynamic_pressure_maxq, mach_maxmach, time_apogee, altitude_apogee, vel_apogee,
            pos_landing, downrange_landing,
            peak_total_aoa, aoa_launch_clear, peak_spin_rate, spin_rate_burnout,
            min_sg, min_resonance_ratio, max_trim_aoa, max_lateral_aero_load)


def post_3sigma_summary(case_number_list, maxQ_Q_list, mach_list, time_apogee_list, altitude_list,
                        vel_apogee_list, downrange_impact_list, file_prefix,
                        peak_total_aoa_list=None, aoa_launch_clear_list=None,
                        peak_spin_rate_list=None, spin_rate_burnout_list=None,
                        min_sg_list=None, min_resonance_ratio_list=None,
                        max_trim_aoa_list=None, max_lateral_aero_load_list=None):
    case_count = len(case_number_list)
    if case_count < 1000:
        return

    txt = open(file_prefix + '_summary.txt', mode='w')

    low_index = int((case_count - (case_count * 0.9973)) / 2)
    if low_index < 1:
        return
    high_index = -low_index - 1

    # State the convention: these are 1-D order statistics of each metric, with no distribution
    # assumption. The impact ellipse of the same run is a 2-D covariance ellipse at k=3, whose
    # containment is 98.89% — a different quantity that also calls itself "3 sigma".
    txt.writelines(['Summary 3sigma Convention,'
                    'empirical 99.73 percentile per metric (1-D order statistic; no Gaussian '
                    'assumption). The impact dispersion ellipse uses k=3 covariance semi-axes '
                    '(2-D containment 98.89%) - see the *_ellipse_summary.txt of this run\n'])

    def _write_3sigma(label, values, unit):
        ind = np.argsort(values)
        cases_sorted = np.array(case_number_list)[ind]
        vals_sorted = np.array(values)[ind]
        txt.writelines([f'{label} 3sigma High Case,', str(cases_sorted[high_index]), '\n'])
        txt.writelines([f'{label} 3sigma High,', str(round(float(vals_sorted[high_index]), 3)), f'[{unit}]\n'])
        txt.writelines([f'{label} 3sigma Low Case,', str(cases_sorted[low_index]), '\n'])
        txt.writelines([f'{label} 3sigma Low,', str(round(float(vals_sorted[low_index]), 3)), f'[{unit}]\n'])

    def _write_reach_probability(label, values, threshold):
        arr = np.asarray(values, dtype=float)
        arr = arr[~np.isnan(arr)]
        if not len(arr):
            return
        prob = float(np.count_nonzero(arr >= threshold)) / len(arr) * 100.0
        txt.writelines([f'{label} Reach Probability >= {threshold * 1e-3:g}km,',
                        str(round(prob, 3)), '[%]\n'])

    _write_3sigma('DynamicPressure', maxQ_Q_list, 'kPa')
    _write_3sigma('MachNumber', mach_list, '-')
    _write_3sigma('Apogee X+', time_apogee_list, 's')
    _write_3sigma('Apogee Altitude', altitude_list, 'm')
    _write_reach_probability('Apogee Altitude', altitude_list, REACH_ALTITUDE_THRESHOLD_M)
    _write_3sigma('Apogee Air Velocity', vel_apogee_list, 'm/s')
    _write_3sigma('Impact Downrange', downrange_impact_list, 'm')

    if peak_total_aoa_list is not None:
        _write_3sigma('Peak Total AoA', peak_total_aoa_list, 'deg')
    if aoa_launch_clear_list is not None:
        _write_3sigma('Launch Clear Total AoA', aoa_launch_clear_list, 'deg')
    if peak_spin_rate_list is not None:
        _write_3sigma('Peak Spin Rate', peak_spin_rate_list, 'deg/s')
    if spin_rate_burnout_list is not None:
        valid = [v for v in spin_rate_burnout_list if not np.isnan(v)]
        if valid:
            _write_3sigma('Spin Rate at Burnout', spin_rate_burnout_list, 'deg/s')
    if min_sg_list is not None:
        _write_3sigma('Min GyroStabilityFactor Sg', min_sg_list, '-')
    if min_resonance_ratio_list is not None:
        _write_3sigma('Min ResonanceRatio', min_resonance_ratio_list, '-')
    if max_trim_aoa_list is not None:
        _write_3sigma('Max TrimAoA', max_trim_aoa_list, 'deg')
    if max_lateral_aero_load_list is not None:
        _write_3sigma('Max LateralAeroLoad', max_lateral_aero_load_list, 'N')

    txt.close()


