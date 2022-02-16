
from runner_tool.json_api import get_parachute_drag_factor, get_secondary_parachute_drag_factor
from runner_tool.json_api import set_parachute_drag_factor, set_secondary_parachute_drag_factor

from runner_tool.dispersion_error_item import ErrorSourceItem

class SoeDispersionConfig:
    def __init__(self, soe_dispersion_param):
        self.para_CdS = ErrorSourceItem(soe_dispersion_param, 'Parachute Drag Factor [m2]')
        self.para_2nd_CdS = ErrorSourceItem(soe_dispersion_param, 'Secondary Parachute Drag Factor [m2]')

    def is_enable_dispersion(self):
        # どれかひとつでもenableならenable返し
        if self.para_CdS.is_enable(): return True
        if self.para_2nd_CdS.is_enable(): return True

    def generate_json_dict(self, soe):
        if self.para_CdS.is_enable():
            CdS = self.para_CdS.get_random_value(get_parachute_drag_factor(soe))
            soe = set_parachute_drag_factor(soe, CdS)
        
        if self.para_2nd_CdS.is_enable():
            CdS = self.para_2nd_CdS.get_random_value(get_secondary_parachute_drag_factor(soe))
            soe = set_secondary_parachute_drag_factor(soe, CdS)

        return soe

