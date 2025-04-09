#!/usr/bin/env python3
import json, time, logging, signal, re

CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"

with open(CONFIG_FILE) as f:
    conf = json.load(f)[SECTION]

TMP_FILE = conf["TMP_FILE"]
REALITY_LOG_FILE = conf["REALITY_LOG_FILE"]
REALITY_CYCLE = conf["REALITY_CYCLE"]

logging.basicConfig(filename=REALITY_LOG_FILE, level=logging.INFO,
    format="%(asctime)s - %(message)s")

running = True
def handle_signal(sig, frame):
    global running
    if sig in [signal.SIGINT, signal.SIGTERM]:
        logging.info("Reality loop exiting due to signal.")
        running = False
signal.signal(signal.SIGINT, handle_signal)
signal.signal(signal.SIGTERM, handle_signal)

def strip_comments_and_parse(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    clean = [re.sub(r'#.*$', '', line).strip() for line in lines if line.strip() and not line.strip().startswith('#')]
    return json.loads('\n'.join(clean))

def write_clean_json(filepath, data):
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
        f.write('\n')

def apply_reality_model(data):
    ir = data.get("input_registers", {})
    co = data.get("coils", {})

    pump_on = int(co.get("0", 0))
    fan_on = int(co.get("2", 0))
    pump_voltage = int(ir.get("0", 0))
    fan_voltage = int(ir.get("4", 0))
    temperature = int(ir.get("1", 55))
    pressure = int(ir.get("2", 900))
    throughput = int(ir.get("3", 100))

    # === New Simulated Values ===
    new_throughput = max(5, min(200, int(0.4 * abs(pump_voltage))))
    if pump_on and pump_voltage > 0:
        new_pressure = min(1600, pressure + int(0.03 * pump_voltage))
    elif pump_on and pump_voltage < 0:
        new_pressure = max(200, pressure + int(0.04 * pump_voltage))  # decrease
    else:
        new_pressure = max(200, pressure - 5)

    if fan_on:
        cooling = int(fan_voltage / (new_throughput + 5)) + 1
        new_temp = max(10, temperature - cooling)
    else:
        heating = int(new_pressure / 500) + 1
        new_temp = min(130, temperature + heating)

    changes = {}
    if new_throughput != throughput:
        ir["3"] = new_throughput
        changes["Throughput"] = (throughput, new_throughput)
    if new_pressure != pressure:
        ir["2"] = new_pressure
        changes["Pressure"] = (pressure, new_pressure)
    if new_temp != temperature:
        ir["1"] = new_temp
        changes["Temperature"] = (temperature, new_temp)

    data["input_registers"] = ir
    return data, changes

def main():
    logging.info("Reality loop started.")
    while running:
        try:
            data = strip_comments_and_parse(TMP_FILE)
            updated, changes = apply_reality_model(data)
            write_clean_json(TMP_FILE, updated)
            for k, (old, new) in changes.items():
                logging.info(f"{k} changed from {old} to {new}")
        except Exception as e:
            logging.error(f"Reality loop error: {e}")
        time.sleep(REALITY_CYCLE)

if __name__ == "__main__":
    main()
