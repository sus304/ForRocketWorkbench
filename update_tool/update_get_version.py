import os
import shutil
import zipfile
import subprocess
import requests
import semantic_version as semver

solver_binaly_name = "ForRocket"
if os.name == 'nt':
    solver_binaly_name += '.exe'

# インストールされているソルバのバージョン取得
def get_installed_solver_version():
    if os.name == 'nt':
        cmd = '.\\' + solver_binaly_name + ' -v'
        p = subprocess.Popen(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        while True:
            line = p.stdout.readline()
            if line:
                try:
                    version_str = line.split('version:')[1].split('(')[0]
                    major_v, minor_v, patch_v = version_str.split('.')
                    return semver.Version(major=int(major_v), minor=int(minor_v), patch=int(patch_v))
                except:
                    pass
            if not line and p.poll() is not None:
                break
    else:
        pass

def get_latest_solver_version():
    try:
        res = requests.get('https://import-avio.com/ForRocket/api/solver/latest/version')
        res_json = res.json()
    except:
        print('Network error.')
        return semver.Version('0.0.0')
    return semver.Version(res_json['string'])

def print_latest_solver_version():
    installed_ver = get_installed_solver_version()
    latest_ver = get_latest_solver_version()
    print('ForRocket latest version: '+str(latest_ver.major)+'.'+str(latest_ver.minor)+'.'+str(latest_ver.patch))
    if latest_ver > installed_ver:
        print('Exist solver update!')
    
def update_solver():
    installed_ver = get_installed_solver_version()
    latest_ver = get_latest_solver_version()
    if latest_ver > installed_ver:
        print('Updating...')
        try:
            res = requests.get('https://import-avio.com/ForRocket/api/solver/latest')
            file_name = res.headers['Content-Disposition'].split('=')[1]
        except:
            print('Network error.')
            return
        try:
            with open(file_name, 'wb') as f:
                f.write(res.content)
        except Exception as e:
            print(e)

        temp_dir = ''
        with zipfile.ZipFile(file_name) as zf:
            temp_dir = zf.namelist()[0]
            zf.extractall()

        file_list = os.listdir(temp_dir)
        for f in file_list:
            shutil.copy2(temp_dir+f, './')
        shutil.rmtree(temp_dir)
        os.remove(file_name)
        print('Complete update.')
    else:
        print('Already update.')

if __name__ == '__main__':
    update_solver()
    

