import os
import shutil
import subprocess

solver_binaly_name = "ForRocket"
if os.name == 'nt':
    solver_binaly_name += '.exe'

def copy_solver_binary(dst_dir):
    shutil.copy2(solver_binaly_name, dst_dir+'/'+solver_binaly_name)

def run_solver(solver_config_json_file_path):
    if os.name == 'nt':
        cmd = '.\\' + solver_binaly_name + ' ' + solver_config_json_file_path
        # print(cmd)
        res = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE)
        # res = subprocess.run([solver_binaly_name, solver_config_json_file_path], shell=False, text=True, stdout=subprocess.PIPE)
        # p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        # while True:
        #     line = p.stdout.readline()
        #     # print(line)
        #     if p.poll() is not None:
        #         break
    else:
        cmd = './' + solver_binaly_name + ' ' + solver_config_json_file_path + ' -v'
        res = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE)

def print_solver_version_string():
    if os.name == 'nt':
        cmd = '.\\' + solver_binaly_name + ' -v'
        p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while True:
            line = p.stdout.readline()
            if line:
                print(line)
            if not line and p.poll() is not None:
                break
    else:
        pass