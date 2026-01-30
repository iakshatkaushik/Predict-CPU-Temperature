import psutil
import time
import csv
import platform
import subprocess
from datetime import datetime
from collections import deque

# --- CONFIGURATION ---
SYSTEM_ID = "S1"
OUTPUT_FILE = f"system_{SYSTEM_ID}.csv"
SAMPLING_INTERVAL = 1.0     # seconds
DURATION = 1800             # 30 minutes
IDLE_THRESHOLD = 5.0        # CPU % considered idle

# --- PLATFORM CHECK ---
if platform.system() != "Darwin":
    print("ERROR: This script is for macOS only.")
    exit(1)

# --- ROLLING BUFFERS ---
cpu_util_10s = deque(maxlen=10)
cpu_util_30s = deque(maxlen=30)
cpu_util_60s = deque(maxlen=60)
cpu_temp_hist = deque(maxlen=5)

last_idle_time = time.time()

# Seed psutil CPU percent
psutil.cpu_percent(interval=None)

freq = psutil.cpu_freq()
CLOCK_SPEED_MAX = freq.max if freq else 0.0


# --- CPU TEMPERATURE (macOS) ---
def get_cpu_temperature_mac():
    # Method 1: psutil (rarely works)
    try:
        temps = psutil.sensors_temperatures()
        if temps:
            for entries in temps.values():
                for entry in entries:
                    if entry.current is not None:
                        return round(entry.current, 2)
    except Exception:
        pass

    # Method 2: osx-cpu-temp (recommended)
    try:
        result = subprocess.run(
            ["osx-cpu-temp"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return round(float(result.stdout.replace("°C", "").strip()), 2)
    except Exception:
        pass

    # Method 3: istats
    try:
        result = subprocess.run(
            ["istats", "cpu", "temp", "--value-only"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            return round(float(result.stdout.strip()), 2)
    except Exception:
        pass

    return None


# --- POWER ESTIMATION ---
def get_voltage_current(cpu_util):
    battery = psutil.sensors_battery()
    if battery:
        voltage = 11.4 if battery.power_plugged else 11.1
        current = 1.5 + (cpu_util / 100.0) * 3.5
    else:
        voltage = 12.0
        current = 2.0 + (cpu_util / 100.0) * 8.0
    return round(voltage, 2), round(current, 2)


# --- AMBIENT TEMPERATURE ---
def get_ambient_temperature(cpu_temp):
    if cpu_temp is not None:
        return round(cpu_temp - 12.0, 2)
    return 25.0


# --- START ---
print(f"Initializing macOS data collection for {SYSTEM_ID}")
print("=" * 60)

test_temp = get_cpu_temperature_mac()
if test_temp is None:
    print("⚠️  CPU temperature not detected.")
    print("Install one of the following:")
    print("  brew install osx-cpu-temp")
    print("  sudo gem install iStats")
    choice = input("Continue WITHOUT CPU temperature? (y/n): ")
    if choice.lower() != "y":
        exit(1)
else:
    print(f"✓ CPU Temperature detected: {test_temp}°C")

print("=" * 60)

with open(OUTPUT_FILE, mode="w", newline="") as file:
    writer = csv.writer(file)

    # --- CSV HEADER (MATCHES WINDOWS SCRIPT) ---
    writer.writerow([
        "timestamp",
        "cpu_util",
        "cpu_util_avg_10s",
        "cpu_util_avg_30s",
        "cpu_util_avg_60s",
        "cpu_util_peak_10s",
        "cpu_util_var_30s",
        "mem_util",
        "clock_speed",
        "clock_speed_max",
        "cpu_temp",
        "cpu_temp_prev_1s",
        "cpu_temp_prev_5s",
        "ambient_temp",
        "voltage",
        "current",
        "power_estimated",
        "power_source",
        "time_since_idle",
        "system_id"
    ])

    start_time = time.time()

    try:
        while (time.time() - start_time) < DURATION:
            loop_start = time.time()

            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cpu_util = psutil.cpu_percent(interval=None)
            mem_util = psutil.virtual_memory().percent

            freq = psutil.cpu_freq()
            clock_speed = freq.current if freq else 0.0

            cpu_temp = get_cpu_temperature_mac()
            ambient_temp = get_ambient_temperature(cpu_temp)

            battery = psutil.sensors_battery()
            power_source = 1 if (not battery or battery.power_plugged) else 0

            voltage, current = get_voltage_current(cpu_util)
            power_estimated = round(voltage * current, 2)

            if cpu_util < IDLE_THRESHOLD:
                last_idle_time = time.time()
            time_since_idle = round(time.time() - last_idle_time, 2)

            cpu_util_10s.append(cpu_util)
            cpu_util_30s.append(cpu_util)
            cpu_util_60s.append(cpu_util)

            avg_10s = round(sum(cpu_util_10s) / len(cpu_util_10s), 2)
            avg_30s = round(sum(cpu_util_30s) / len(cpu_util_30s), 2)
            avg_60s = round(sum(cpu_util_60s) / len(cpu_util_60s), 2)
            peak_10s = round(max(cpu_util_10s), 2)
            var_30s = round(
                sum((x - avg_30s) ** 2 for x in cpu_util_30s) / len(cpu_util_30s), 2
            )

            temp_prev_1s = cpu_temp_hist[-1] if len(cpu_temp_hist) >= 1 else None
            temp_prev_5s = cpu_temp_hist[0] if len(cpu_temp_hist) == 5 else None
            if cpu_temp is not None:
                cpu_temp_hist.append(cpu_temp)

            writer.writerow([
                timestamp,
                cpu_util,
                avg_10s,
                avg_30s,
                avg_60s,
                peak_10s,
                var_30s,
                mem_util,
                clock_speed,
                CLOCK_SPEED_MAX,
                cpu_temp,
                temp_prev_1s,
                temp_prev_5s,
                ambient_temp,
                voltage,
                current,
                power_estimated,
                power_source,
                time_since_idle,
                SYSTEM_ID
            ])

            temp_str = f"{cpu_temp:.1f}°C" if cpu_temp else "N/A"
            print(
                f"\r[{SYSTEM_ID}] CPU: {cpu_util:5.1f}% | Temp: {temp_str:>6} | IdleΔ: {time_since_idle:6.1f}s",
                end="",
                flush=True
            )

            elapsed = time.time() - loop_start
            time.sleep(max(0, SAMPLING_INTERVAL - elapsed))

    except KeyboardInterrupt:
        print("\nInterrupted by user.")

print("\n" + "=" * 60)
print(f"Data collection completed. Saved to {OUTPUT_FILE}")
