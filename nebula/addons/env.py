import logging
import os
import platform
import re
import sys

import requests

from nebula import __version__


def check_version():
    # Check version of NEBULA (__version__ is defined in __init__.py) and compare with __version__ in https://raw.githubusercontent.com/CyberDataLab/nebula/main/nebula/__init__.py
    logging.info("Checking NEBULA version...")
    try:
        r = requests.get("https://raw.githubusercontent.com/CyberDataLab/nebula/main/nebula/__init__.py")
        if r.status_code == 200:
            version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', r.text, re.MULTILINE).group(1)
            if version != __version__:
                logging.info(
                    f"Your NEBULA version is {__version__} and the latest version is {version}. Please update your NEBULA version."
                )
                logging.info(
                    "You can update your NEBULA version downloading the latest version from https://github.com/CyberDataLab/nebula"
                )
                sys.exit(0)
            else:
                logging.info(f"Your NEBULA version is {__version__} and it is the latest version.")
    except Exception as e:
        logging.exception(f"Error while checking NEBULA version: {e}")
        sys.exit(0)


def check_environment():
    logging.info(f"NEBULA Platform version: {__version__}")
    # check_version()

    logging.info("======== Running Environment ========")
    logging.info("OS: " + platform.platform())
    logging.info("Hardware: " + platform.machine())
    logging.info("Python version: " + sys.version)

    try:
        import torch

        logging.info("PyTorch version: " + torch.__version__)
    except ImportError:
        logging.info("PyTorch is not installed properly")
    except Exception:
        pass

    logging.info("======== CPU Configuration ========")
    try:
        import psutil

        load1, load5, load15 = psutil.getloadavg()
        cpu_usage = (load15 / os.cpu_count()) * 100

        logging.info(f"The CPU usage is : {cpu_usage:.0f}%")
        logging.info(
            f"Available CPU Memory: {psutil.virtual_memory().available / 1024 / 1024 / 1024:.1f} G / {psutil.virtual_memory().total / 1024 / 1024 / 1024}G"
        )
    except ImportError:
        logging.info("No CPU information available")
    except Exception:
        pass

    if sys.platform == "win32" or sys.platform == "linux":
        logging.info("======== GPU Configuration ========")
        try:
            import pynvml

            pynvml.nvmlInit()
            devices = pynvml.nvmlDeviceGetCount()
            for i in range(devices):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                gpu_percent = pynvml.nvmlDeviceGetUtilizationRates(handle).gpu
                gpu_temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                gpu_mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpu_mem_percent = gpu_mem.used / gpu_mem.total * 100
                gpu_power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                gpu_clocks = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_SM)
                gpu_memory_clocks = pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM)
                gpu_utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
                gpu_fan_speed = pynvml.nvmlDeviceGetFanSpeed(handle)
                logging.info(f"GPU{i} percent: {gpu_percent}")
                logging.info(f"GPU{i} temp: {gpu_temp}")
                logging.info(f"GPU{i} mem percent: {gpu_mem_percent}")
                logging.info(f"GPU{i} power: {gpu_power}")
                logging.info(f"GPU{i} clocks: {gpu_clocks}")
                logging.info(f"GPU{i} memory clocks: {gpu_memory_clocks}")
                logging.info(f"GPU{i} utilization: {gpu_utilization.gpu}")
                logging.info(f"GPU{i} fan speed: {gpu_fan_speed}")
        except ImportError:
            logging.info("pynvml module not found, GPU information unavailable")
        except Exception:
            pass
    else:
        logging.info("GPU information unavailable")
