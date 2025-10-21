#!/usr/bin/env python3
import json, time, os, re, logging, sys, random

# === SYSTEM REACTIVITY CONTROL ===
AGGRESSIVENESS = 0.6  # 1.0 = normal; <1.0 = more stable; >1.0 = more volatile

CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"

def strip_comments(text):
    lines = text.splitlines()
    clean = [re.sub(r'#.*$', '', line).strip() for line in lines if line.strip() and not line.strip().startswith('#')]
    return json.loads('\n'.join(clean))

def read_json_strip_comments(filepath):
    with open(filepath) as f:
        return strip_comments(f.read())

def write_atomic(filepath, data):
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, filepath)

with open(CONFIG_FILE) as f:
    conf = json.load(f)[SECTION]

SRC_FILE = conf["JSON_FILE"]
DST_FILE = conf["TMP_FILE"]
REALITY_LOG_FILE = conf.get("REALITY_LOG_FILE", "modbus-reality.log")
REALITY_CYCLE = conf.get("REALITY_CYCLE", 1)
SILENT = "--silent" in sys.argv

logging.basicConfig(filename=REALITY_LOG_FILE, level=logging.INFO,
    format='%(asctime)s - %(message)s')

def clamp(val, minval, maxval):
    return max(minval, min(maxval, val))

def run_reality_loop():
    if not os.path.exists(DST_FILE):
        src_data = read_json_strip_comments(SRC_FILE)
        write_atomic(DST_FILE, src_data)
        if not SILENT:
            print(f"Generated {DST_FILE} from {SRC_FILE}")

    print(f"Reality loop: src={SRC_FILE}, dst={DST_FILE}, interval={REALITY_CYCLE}s")

    while True:
        try:
            data = read_json_strip_comments(DST_FILE)
        except Exception as e:
            logging.warning(f"Could not read TMP file: {e}")
            time.sleep(REALITY_CYCLE)
            continue

        ir = data.get("input_registers", {})
        hr = data.get("holding_registers", {})
        coils = data.get("coils", {})

        pump_voltage = ir.get("0", 0)
        temperature = ir.get("1", 55)
        pressure = ir.get("2", 900)
        throughput = ir.get("3", 100)
        fan_rpm = ir.get("4", 0)
        heater_power = ir.get("5", 0)

        fan_on = coils.get("2", 0)
        heater_on = coils.get("3", 0)
        valve_open = coils.get("5", 0)
        relief_threshold = hr.get("6", 1300)
        bleed_rate = hr.get("7", 15)

        # === THROUGHPUT ===
        max_throughput = clamp(pump_voltage, 0, 1000)
        temp_penalty = max(0.0, (temperature - 70) / 100)
        raw_throughput = max_throughput * (1 - temp_penalty)
        new_throughput = clamp(int(max(raw_throughput, 20)), 20, 1000)
        new_throughput = int(new_throughput * AGGRESSIVENESS)

        # === PRESSURE ===
        pressure_input = (new_throughput / 100) ** 1.2 * 10
        pressure_loss = (throughput / 120) ** 1.1 * 7
        pressure_delta = (pressure_input - pressure_loss) * AGGRESSIVENESS
        new_pressure = pressure + pressure_delta

        # Apply relief valve if open
        if valve_open and pressure > relief_threshold:
            new_pressure -= bleed_rate
            logging.info(f"Pressure relief valve OPEN: bleeding {bleed_rate} (pressure {int(pressure)} -> {int(new_pressure)})")

        new_pressure = clamp(int(new_pressure), 600, 1400)

        # === TEMPERATURE ===
        heat_from_pump = (pump_voltage / 1000) ** 1.5 * 25
        heat_from_pressure = ((pressure - 800) / 400) ** 2 * 20 if pressure > 800 else 0
        heat_from_heater = (heater_power / 200) ** 1.2 * 40 if heater_on else 0
        cooling_from_fan = (fan_rpm / 300) ** 1.4 * 60 if fan_on else 0

        temp_delta = (heat_from_pump + heat_from_pressure + heat_from_heater - cooling_from_fan)
        temp_delta *= AGGRESSIVENESS
        noise = random.uniform(-1, 1)
        new_temperature = clamp(int(temperature + temp_delta + noise), 30, 150)

        # === LOGGING AND UPDATE ===
        updates = {}
        if new_throughput != throughput:
            ir["3"] = new_throughput
            updates["Throughput"] = (throughput, new_throughput)
        if new_pressure != pressure:
            ir["2"] = new_pressure
            updates["Pressure"] = (pressure, new_pressure)
        if new_temperature != temperature:
            ir["1"] = new_temperature
            updates["Temperature"] = (temperature, new_temperature)

        data["input_registers"] = ir
        if updates:
            write_atomic(DST_FILE, data)
            for what, (old, new) in updates.items():
                msg = f"{what} changed from {old} to {new}"
                logging.info(msg)
                if not SILENT:
                    print(msg)

        time.sleep(REALITY_CYCLE)

if __name__ == "__main__":
    run_reality_loop()
