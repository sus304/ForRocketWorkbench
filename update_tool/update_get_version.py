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
    if os.name != 'nt':
        return semver.Version('0.0.0')
    try:
        res = subprocess.run(
            ['.\\' + solver_binaly_name, '-v'],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        print(f'Failed to query installed solver: {e}')
        return semver.Version('0.0.0')
    for line in res.stdout.splitlines():
        try:
            version_str = line.split('version:')[1].split('(')[0]
            major_v, minor_v, patch_v = version_str.split('.')
            return semver.Version(major=int(major_v), minor=int(minor_v), patch=int(patch_v))
        except (IndexError, ValueError):
            continue
    return semver.Version('0.0.0')

def get_latest_solver_version():
    try:
        res = requests.get('https://import-avio.com/ForRocket/api/solver/latest/version', timeout=10)
        res_json = res.json()
    except (requests.RequestException, ValueError) as e:
        print(f'Network error: {e}')
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
    if latest_ver <= installed_ver:
        print('Already update.')
        return

    print('Updating...')
    try:
        res = requests.get('https://import-avio.com/ForRocket/api/solver/latest', timeout=30)
        file_name = res.headers['Content-Disposition'].split('=')[1].strip('"')
    except (requests.RequestException, KeyError, IndexError) as e:
        print(f'Network error: {e}')
        return

    temp_dir = None
    try:
        with open(file_name, 'wb') as f:
            f.write(res.content)

        with zipfile.ZipFile(file_name) as zf:
            temp_dir = zf.namelist()[0]
            zf.extractall()

        for f in os.listdir(temp_dir):
            shutil.copy2(os.path.join(temp_dir, f), '.')
        print('Complete update.')
    except (OSError, zipfile.BadZipFile) as e:
        print(f'Update failed: {e}')
    finally:
        if temp_dir and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(file_name):
            os.remove(file_name)

if __name__ == '__main__':
    update_solver()
    

