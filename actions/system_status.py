"""
SAM System Status Action
Reports real-time CPU, RAM, GPU, Disk, Battery, and Uptime metrics.
"""
from __future__ import annotations

import time
import psutil
from typing import Any, Dict


def _format_bytes(byte_count: float) -> str:
    gb = byte_count / (1024 ** 3)
    return f"{gb:.1f} GB"


def get_hardware_status() -> Dict[str, Any]:
    # CPU
    cpu_percent = psutil.cpu_percent(interval=0.1)
    cpu_count = psutil.cpu_count(logical=True)

    # Memory
    vm = psutil.virtual_memory()
    ram_percent = vm.percent
    ram_used = _format_bytes(vm.used)
    ram_total = _format_bytes(vm.total)

    # Disk (system drive)
    try:
        disk = psutil.disk_usage("C:\\")
        disk_free = _format_bytes(disk.free)
        disk_total = _format_bytes(disk.total)
        disk_percent = disk.percent
    except Exception:
        disk_percent, disk_free, disk_total = 0, "Unknown", "Unknown"

    # Battery
    battery_info = "Desktop / AC power"
    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            plugged = "plugged in" if battery.power_plugged else "on battery"
            battery_info = f"{battery.percent:.0f}% ({plugged})"
    except Exception:
        pass

    # Boot time / Uptime
    try:
        boot_seconds = time.time() - psutil.boot_time()
        hours = int(boot_seconds // 3600)
        minutes = int((boot_seconds % 3600) // 60)
        uptime_str = f"{hours}h {minutes}m"
    except Exception:
        uptime_str = "Unavailable"

    return {
        "cpu_percent": cpu_percent,
        "cpu_count": cpu_count,
        "ram_percent": ram_percent,
        "ram_used": ram_used,
        "ram_total": ram_total,
        "disk_percent": disk_percent,
        "disk_free": disk_free,
        "disk_total": disk_total,
        "battery": battery_info,
        "uptime": uptime_str,
    }


def system_status(params: Dict[str, Any] | None = None) -> str:
    """Entrypoint for SAM LLM tool call: system_status."""
    status = get_hardware_status()

    return (
        f"System Telemetry: CPU is at {status['cpu_percent']}%, RAM load is {status['ram_percent']}% "
        f"({status['ram_used']} used of {status['ram_total']}), Disk C has {status['disk_free']} free "
        f"({status['disk_percent']}% used), Battery is {status['battery']}, and system uptime is {status['uptime']}."
    )


if __name__ == "__main__":
    print(system_status({}))
