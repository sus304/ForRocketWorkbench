import numpy as np
from scipy import stats

class ErrorSourceItem:
    def __init__(self, dsp_param_json_dict, item_name):
        # enable
        # 標準偏差
        # 信頼区間
        self.enable = dsp_param_json_dict.get(item_name).get('Enable')
        self.std = dsp_param_json_dict.get(item_name).get('Standard Deviation')
        self.p = dsp_param_json_dict.get(item_name).get('Confidence interval')

    def is_enable(self):
        return self.enable

    def get_random_value(self, mean_value):
        one_side_non_p_area = (1.0 - self.p) * 0.5  # 分布の信頼区間外の片側
        func_p_value = one_side_non_p_area + self.p  # 分布関数のy値
        n_sigma = stats.norm.ppf(func_p_value)

        upper_limit = -1 * self.std * n_sigma
        lower_limit = self.std * n_sigma
        return stats.truncnorm.rvs(upper_limit/self.std, lower_limit/self.std, loc=mean_value, scale=self.std)

        # 信頼区間を切らない場合
        # return stats.norm.rvs(loc=mean_value, scale=self.std)

    def get_random_values(self, mean_value, size):
        one_side_non_p_area = (1.0 - self.p) * 0.5  # 分布の信頼区間外の片側
        func_p_value = one_side_non_p_area + self.p  # 分布関数のy値
        n_sigma = stats.norm.ppf(func_p_value)

        upper_limit = -1 * self.std * n_sigma
        lower_limit = self.std * n_sigma
        return stats.truncnorm.rvs(upper_limit/self.std, lower_limit/self.std, loc=mean_value, scale=self.std, size=size)

        # 信頼区間を切らない場合
        # return stats.norm.rvs(loc=mean_value, scale=self.std, size=size)

    def get_random_values_from_array(self, value_array):
        one_side_non_p_area = (1.0 - self.p) * 0.5  # 分布の信頼区間外の片側
        func_p_value = one_side_non_p_area + self.p  # 分布関数のy値
        n_sigma = stats.norm.ppf(func_p_value)

        upper_limit = -1 * self.std * n_sigma
        lower_limit = self.std * n_sigma
        rv = stats.truncnorm.rvs(upper_limit/self.std, lower_limit/self.std, scale=self.std)
        # array全体を通して同じ乱数のために先に生成

        return np.array([rv + v for v in value_array])


