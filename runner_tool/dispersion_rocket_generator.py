import numpy as np

from runner_tool.json_api import _file_copy_by_param
from runner_tool.json_api import get_mass_inert, set_mass_inert
from runner_tool.json_api import get_mass_prop, set_mass_prop
from runner_tool.json_api import xcg_file_is_enable
from runner_tool.json_api import get_xcg_file_name, set_xcg_file_name
from runner_tool.json_api import get_constant_xcg, set_constant_xcg
from runner_tool.json_api import moi_file_is_enable
from runner_tool.json_api import get_moi_file_name, set_moi_file_name
from runner_tool.json_api import get_constant_moi_yaw, set_constant_moi_yaw
from runner_tool.json_api import get_constant_moi_pitch, set_constant_moi_pitch
from runner_tool.json_api import get_constant_moi_roll, set_constant_moi_roll
from runner_tool.json_api import xcp_file_is_enable
from runner_tool.json_api import get_xcp_file_name, set_xcp_file_name
from runner_tool.json_api import get_constant_xcp, set_constant_xcp
from runner_tool.json_api import CA_file_is_enable
from runner_tool.json_api import get_CA_file_name, set_CA_file_name
from runner_tool.json_api import get_constant_CA, set_constant_CA
from runner_tool.json_api import get_burnoutCA_file_name, set_burnoutCA_file_name
from runner_tool.json_api import get_constant_burnoutCA, set_constant_burnoutCA
from runner_tool.json_api import CNa_file_is_enable
from runner_tool.json_api import get_CNa_file_name, set_CNa_file_name
from runner_tool.json_api import get_constant_CNa, set_constant_CNa
from runner_tool.json_api import get_cant_angle, set_cant_angle
from runner_tool.json_api import Cld_file_is_enable
from runner_tool.json_api import get_Cld_file_name, set_Cld_file_name
from runner_tool.json_api import get_constant_Cld, set_constant_Cld
from runner_tool.json_api import Clp_file_is_enable
from runner_tool.json_api import get_Clp_file_name, set_Clp_file_name
from runner_tool.json_api import get_constant_Clp, set_constant_Clp
from runner_tool.json_api import Cmq_file_is_enable
from runner_tool.json_api import get_Cmq_file_name, set_Cmq_file_name
from runner_tool.json_api import get_constant_Cmq, set_constant_Cmq
from runner_tool.json_api import Cnr_file_is_enable
from runner_tool.json_api import get_Cnr_file_name, set_Cnr_file_name
from runner_tool.json_api import get_constant_Cnr, set_constant_Cnr


from runner_tool.dispersion_error_item import ErrorSourceItem

class RocketDispersionConfig:
    def __init__(self, rocket_dispersion_param):
        self.mass_inert = ErrorSourceItem(rocket_dispersion_param, 'Mass Inert [kg]')
        self.mass_prop = ErrorSourceItem(rocket_dispersion_param, 'Mass Propellant [kg]')
        self.xcg = ErrorSourceItem(rocket_dispersion_param, 'X-C.G. [mm]')
        self.moi_yaw = ErrorSourceItem(rocket_dispersion_param, 'M.I. Yaw Axis [kg-m2]')
        self.moi_pitch = ErrorSourceItem(rocket_dispersion_param, 'M.I. Pitch Axis [kg-m2]')
        self.moi_roll = ErrorSourceItem(rocket_dispersion_param, 'M.I. Roll Axis [kg-m2]')
        self.xcp = ErrorSourceItem(rocket_dispersion_param, 'X-C.P. [mm]')
        self.CA = ErrorSourceItem(rocket_dispersion_param, 'CA')
        self.CNa = ErrorSourceItem(rocket_dispersion_param, 'CNa')
        self.Cld = ErrorSourceItem(rocket_dispersion_param, 'Cld')
        self.cant_angle = ErrorSourceItem(rocket_dispersion_param, 'Fin Cant Angle [deg]')
        self.Clp = ErrorSourceItem(rocket_dispersion_param, 'Clp')
        self.Cmq = ErrorSourceItem(rocket_dispersion_param, 'Cmq')
        self.Cnr = ErrorSourceItem(rocket_dispersion_param, 'Cnr')

    def is_enable_dispersion(self):
        return True
        # 必要なcsvをコピーするために無条件True
        # if self.mass_inert.is_enable(): return True
        # if self.mass_prop.is_enable(): return True
        # if self.xcg.is_enable(): return True
        # if self.moi_yaw.is_enable(): return True
        # if self.moi_pitch.is_enable(): return True
        # if self.moi_roll.is_enable(): return True
        # if self.xcp.is_enable(): return True
        # if self.CA.is_enable(): return True
        # if self.CNa.is_enable(): return True
        # if self.Cld.is_enable(): return True
        # if self.cant_angle.is_enable(): return True
        # if self.Clp.is_enable(): return True
        # if self.Cmq.is_enable(): return True
        # if self.Cnr.is_enable(): return True

    def generate_json_dict(self, rocket_param, dst_dir, case_num):
        if self.mass_inert.is_enable():
            mass = self.mass_inert.get_random_value(get_mass_inert(rocket_param))
            rocket_param = set_mass_inert(rocket_param, mass)
        
        if self.mass_prop.is_enable():
            mass = self.mass_prop.get_random_value(get_mass_prop(rocket_param))
            rocket_param = set_mass_prop(rocket_param, mass)

        if self.xcg.is_enable():
            if xcg_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_xcg_file_name(rocket_param), delimiter=',', skiprows=1)
                xcg_array = self.xcg.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], xcg_array]
                save_csv_name = str(case_num)+'_'+get_xcg_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Xcg', comments='')
                rocket_param = set_xcg_file_name(rocket_param, save_csv_name)
            else:
                xcg = self.xcg.get_random_value(get_constant_xcg(rocket_param))
                rocket_param = set_constant_xcg(rocket_param, xcg)
        else:
            _file_copy_by_param(rocket_param, 'Enable X-C.G. File', 'X-C.G. File', 'X-C.G. File Path', dst_dir)

        if self.moi_yaw.is_enable() == False and self.moi_pitch.is_enable() == False and self.moi_roll.is_enable() == False:
            _file_copy_by_param(rocket_param, 'Enable M.I. File', 'M.I. File', 'M.I. File Path', dst_dir)
        else:
            if moi_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_moi_file_name(rocket_param), delimiter=',', skiprows=1)

                if self.moi_yaw.is_enable():
                    moi_yaw_array = self.moi_yaw.get_random_values_from_array(load_array[:,1])
                else:
                    moi_yaw_array = load_array[:,1]
                if self.moi_pitch.is_enable():
                    moi_pitch_array = self.moi_pitch.get_random_values_from_array(load_array[:,2])
                else:
                    moi_pitch_array = load_array[:,2]
                if self.moi_roll.is_enable():
                    moi_roll_array = self.moi_roll.get_random_values_from_array(load_array[:,3])
                else:
                    moi_roll_array = load_array[:,3]
                
                save_array = np.c_[load_array[:,0], moi_yaw_array, moi_pitch_array, moi_roll_array]
                save_csv_name = str(case_num)+'_'+get_moi_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,y,p,r', comments='')
                rocket_param = set_moi_file_name(rocket_param, save_csv_name)
            else:
                if self.moi_yaw.is_enable():
                    moi = self.moi_yaw.get_random_value(get_constant_moi_yaw(rocket_param))
                    rocket_param = set_constant_moi_yaw(rocket_param, moi)
                if self.moi_pitch.is_enable():
                    moi = self.moi_pitch.get_random_value(get_constant_moi_pitch(rocket_param))
                    rocket_param = set_constant_moi_pitch(rocket_param, moi)
                if self.moi_roll.is_enable():
                    moi = self.moi_roll.get_random_value(get_constant_moi_roll(rocket_param))
                    rocket_param = set_constant_moi_roll(rocket_param, moi)


        if self.xcp.is_enable():
            if xcp_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_xcp_file_name(rocket_param), delimiter=',', skiprows=1)
                xcp_array = self.xcp.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], xcp_array]
                save_csv_name = str(case_num)+'_'+get_xcp_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Xcp', comments='')
                rocket_param = set_xcp_file_name(rocket_param, save_csv_name)
            else:
                xcp = self.xcp.get_random_value(get_constant_xcp(rocket_param))
                rocket_param = set_constant_xcp(rocket_param, xcp)
        else:
            _file_copy_by_param(rocket_param, 'Enable X-C.P. File', 'X-C.P. File', 'X-C.P. File Path', dst_dir)

        if self.CA.is_enable():
            if CA_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_CA_file_name(rocket_param), delimiter=',', skiprows=1)
                CA_array = self.CA.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], CA_array]
                save_csv_name = str(case_num)+'_'+get_CA_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,CA', comments='')
                rocket_param = set_CA_file_name(rocket_param, save_csv_name)
                
                load_array = np.loadtxt(get_burnoutCA_file_name(rocket_param), delimiter=',', skiprows=1)
                burnoutCA_array = self.CA.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], burnoutCA_array]
                save_csv_name = str(case_num)+'_'+get_burnoutCA_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,bCA', comments='')
                rocket_param = set_burnoutCA_file_name(rocket_param, save_csv_name)
            else:
                CA = self.CA.get_random_value(get_constant_CA(rocket_param))
                rocket_param = set_constant_CA(rocket_param, CA)
                
                burnoutCA = self.CA.get_random_value(get_constant_burnoutCA(rocket_param))
                rocket_param = set_constant_burnoutCA(rocket_param, burnoutCA)
        else:
            _file_copy_by_param(rocket_param, 'Enable CA File', 'CA File', 'CA File Path', dst_dir)
            _file_copy_by_param(rocket_param, 'Enable CA File', 'CA File', 'BurnOut CA File Path', dst_dir)

        if self.CNa.is_enable():
            if CNa_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_CNa_file_name(rocket_param), delimiter=',', skiprows=1)
                CNa_array = self.CNa.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], CNa_array]
                save_csv_name = str(case_num)+'_'+get_CNa_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,CNa', comments='')
                rocket_param = set_CNa_file_name(rocket_param, save_csv_name)
            else:
                CNa = self.CNa.get_random_value(get_constant_CNa(rocket_param))
                rocket_param = set_constant_CNa(rocket_param, CNa)
        else:
            _file_copy_by_param(rocket_param, 'Enable CNa File', 'CNa File', 'CNa File Path', dst_dir)


        if self.cant_angle.is_enable():
            cant_angle = self.cant_angle.get_random_value(get_cant_angle(rocket_param))
            rocket_param = set_cant_angle(rocket_param, cant_angle)

        if self.Cld.is_enable():
            if Cld_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_Cld_file_name(rocket_param), delimiter=',', skiprows=1)
                Cld_array = self.Cld.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], Cld_array]
                save_csv_name = str(case_num)+'_'+get_Cld_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Cld', comments='')
                rocket_param = set_Cld_file_name(rocket_param, save_csv_name)
            else:
                Cld = self.Cld.get_random_value(get_constant_Cld(rocket_param))
                rocket_param = set_constant_Cld(rocket_param, Cld)
        else:
            _file_copy_by_param(rocket_param, 'Enable Cld File', 'Cld File', 'CldFile Path', dst_dir)

        if self.Clp.is_enable():
            if Clp_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_Clp_file_name(rocket_param), delimiter=',', skiprows=1)
                Clp_array = self.Clp.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], Clp_array]
                save_csv_name = str(case_num)+'_'+get_Clp_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Clp', comments='')
                rocket_param = set_Clp_file_name(rocket_param, save_csv_name)
            else:
                Clp = self.Clp.get_random_value(get_constant_Clp(rocket_param))
                rocket_param = set_constant_Clp(rocket_param, Clp)
        else:
            _file_copy_by_param(rocket_param, 'Enable Clp File', 'Clp File', 'Clp File Path', dst_dir)

        if self.Cmq.is_enable():
            if Cmq_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_Cmq_file_name(rocket_param), delimiter=',', skiprows=1)
                Cmq_array = self.Cmq.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], Cmq_array]
                save_csv_name = str(case_num)+'_'+get_Cmq_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Cmq', comments='')
                rocket_param = set_Cmq_file_name(rocket_param, save_csv_name)
            else:
                Cmq = self.Cmq.get_random_value(get_constant_Cmq(rocket_param))
                rocket_param = set_constant_Cmq(rocket_param, Cmq)
        else:
            _file_copy_by_param(rocket_param, 'Enable Cmq File', 'Cmq File', 'Cmq File Path', dst_dir)

        if self.Cnr.is_enable():
            if Cnr_file_is_enable(rocket_param):
                load_array = np.loadtxt(get_Cnr_file_name(rocket_param), delimiter=',', skiprows=1)
                Cnr_array = self.Cnr.get_random_values_from_array(load_array[:,1])
                save_array = np.c_[load_array[:,0], Cnr_array]
                save_csv_name = str(case_num)+'_'+get_Cnr_file_name(rocket_param)
                np.savetxt(dst_dir+save_csv_name, save_array, delimiter=',', fmt='%0.4f', header='t,Cnr', comments='')
                rocket_param = set_Cnr_file_name(rocket_param, save_csv_name)
            else:
                Cnr = self.Cnr.get_random_value(get_constant_Cnr(rocket_param))
                rocket_param = set_constant_Cnr(rocket_param, Cnr)
        else:
            _file_copy_by_param(rocket_param, 'Enable Cnr File', 'Cnr File', 'Cnr File Path', dst_dir)


        return rocket_param





