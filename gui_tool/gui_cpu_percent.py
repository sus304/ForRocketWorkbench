import psutil

def get_cpu_percent():
    return psutil.cpu_percent(interval=None)

def get_cpu_freq():
    return psutil.cpu_freq()[0]/1e3

def get_cpu_core():
    return psutil.cpu_count(logical=False)

def get_cpu_thread():
    return psutil.cpu_count()


if __name__ == '__main__':
    print(str(get_cpu_freq()))
    print(str(get_cpu_percent()))
    print(get_cpu_core())
    print(get_cpu_thread())