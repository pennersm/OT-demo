#!/usr/bin/env python3
import json, time, os, re, logging
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.datastore.store import ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification

# === CONFIGURATION LOAD ===
CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"
with open(CONFIG_FILE) as f:
    conf = json.load(f)[SECTION]

JSON_FILE = conf["JSON_FILE"]
TMP_FILE = conf["TMP_FILE"]
LOG_FILE = conf["PLC_LOG_FILE"]
PRINT_STATUS_CYCLE = conf["PRINT_STATUS_CYCLE"]
PLC_LOOP_MULTIPLIER = conf["PLC_LOOP_MULTIPLIER"]
MEMORY_VIEW = conf["MEMORY_VIEW"]
PLC_CYCLE = PRINT_STATUS_CYCLE * PLC_LOOP_MULTIPLIER

# === LOGGING ===
logging.basicConfig(filename=LOG_FILE, filemode='w', level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s')

# === LABELS ===
LABELS = {
    "coils": {
        0: "Pump (coil 0)",
        1: "Alarm (coil 1)",
        2: "Fan (coil 2)",
        3: "Emergency Stop (coil 3)"
    },
    "discrete_inputs": {
        0: "Door Closed (di 0)",
        1: "Safety OK (di 1)",
        2: "Fan Active (di 2)"
    },
    "input_registers": {
        0: "Pump Voltage (ir 0)",
        1: "Temperature (ir 1)",
        2: "Pressure (ir 2)",
        3: "Throughput (ir 3)",
        4: "Fan Voltage (ir 4)"
    },
    "holding_registers": {
        0: "Fan Power (hr 0)",
        1: "Target Temperature (hr 1)",
        2: "Target Pressure (hr 2)",
        3: "Alarm Temp Threshold (hr 3)",
        4: "Alarm Pressure Threshold (hr 4)",
        5: "Mode (hr 5)"
    }
}
def strip_comments(text):
    lines = text.splitlines()
    clean = [re.sub(r'#.*$', '', line).strip() for line in lines if not line.strip().startswith('#')]
    return json.loads('\n'.join([l for l in clean if l]))

def read_json_strip_comments(filepath):
    with open(filepath) as f:
        return strip_comments(f.read())

def write_tmp_file(data):
    with open(TMP_FILE, "w") as f:
        json.dump(data, f, indent=2)

def write_tmp_file_filtered(context):
    filtered = {}
    for section, fc in [("coils", 1), ("discrete_inputs", 2), ("holding_registers", 3), ("input_registers", 4)]:
        filtered[section] = {}
        for i in modbus_memory_labels[section].keys():
            value = context[0].getValues(fc, i, 1)[0]
            filtered[section][str(i)] = value
    with open(TMP_FILE, "w") as f:
        json.dump(filtered, f, indent=2)




def update_modbus_memory(context, data):
    for name, fc in [("coils", 1), ("discrete_inputs", 2), ("holding_registers", 3), ("input_registers", 4)]:
        context[0].setValues(fc, 0, [data.get(name, {}).get(str(i), 0) for i in range(100)])

def read_modbus_memory(context):
    out = {}
    for name, fc in [("coils", 1), ("discrete_inputs", 2), ("holding_registers", 3), ("input_registers", 4)]:
        out[name] = {str(i): context[0].getValues(fc, i, 1)[0] for i in range(100)}
    return out

def print_snapshot(context, iteration, view):
    def b(v): return "ON" if v == 1 else "OFF" if v == 0 else "unknown"
    c = lambda fc: context[0].getValues(fc, 0, 100)
    co, di, ir, hr = c(1), c(2), c(4), c(3)

    print("\033[H\033[J", end="")
    print(f"======== {view} VIEW — PLC STATUS ITERATION: {iteration} ========")
    print("COILS:")
    for i, label in LABELS["coils"].items():
        print(f"  - {label:<35}: {b(co[i])}")
    print("\nDISCRETE INPUTS:")
    for i, label in LABELS["discrete_inputs"].items():
        print(f"  - {label:<35}: {b(di[i])}")
    print("\nINPUT REGISTERS:")
    for i, label in LABELS["input_registers"].items():
        print(f"  - {label:<35}: {ir[i]}")
    print("\nHOLDING REGISTERS:")
    for i, label in LABELS["holding_registers"].items():
        print(f"  - {label:<35}: {hr[i]}")
    print("="*60)

def plc_logic(context):
    ir = context[0].getValues(4, 0, 10)  # Input Registers
    hr = context[0].getValues(3, 0, 10)  # Holding Registers
    co = context[0].getValues(1, 0, 10)  # Coils
    changes = {}

    # === Read sensor values ===
    pump_voltage = ir[0]
    temperature = ir[1]
    pressure = ir[2]
    throughput = ir[3]
    fan_voltage = ir[4]

    # === Read configuration/target values ===
    fan_power = hr[0]  # Not used in control directly
    target_temp = hr[1]
    target_pressure = hr[2]
    alarm_temp = hr[3]
    alarm_pressure = hr[4]
    mode = hr[5]

    # === Emergency Stop ===
    if co[3] == 1:  # Emergency stop is ON
        if pump_voltage != 0:
            context[0].setValues(4, 0, [0])
            changes["Emergency: Pump Voltage"] = (pump_voltage, 0)
        if fan_voltage != 0:
            context[0].setValues(4, 4, [0])
            changes["Emergency: Fan Voltage"] = (fan_voltage, 0)
        logging.warning("Emergency stop active — pump and fan shut down.")
        return  # Skip normal logic

    # === Skip logic if mode is idle ===
    if mode == 0:
        logging.info("PLC logic skipped: mode is idle.")
        return

    # === Pump Voltage Adjustment ===
    new_pump_voltage = pump_voltage
    if pressure > target_pressure + 10:
        new_pump_voltage = max(0, pump_voltage - 28) 
    elif pressure > target_pressure + 5:
        new_pump_voltage = max(0, pump_voltage - 8)
    elif pressure < target_pressure - 10:
        new_pump_voltage = min(1000, pump_voltage + 28)
    elif pressure < target_pressure - 5:
        new_pump_voltage = min(1000, pump_voltage + 8)

    if new_pump_voltage != pump_voltage:
        context[0].setValues(4, 0, [new_pump_voltage])
        changes["Pump Voltage"] = (pump_voltage, new_pump_voltage)

    # === Fan Voltage Adjustment ===
    new_fan_voltage = fan_voltage
    if temperature > target_temp + 3:
        new_fan_voltage = min(1000, fan_voltage + 10)
    elif temperature > target_temp + 1:
        new_fan_voltage = min(1000, fan_voltage + 5)
    elif temperature < target_temp - 3:
        new_fan_voltage = max(0, fan_voltage - 10)
    elif temperature < target_temp - 1:
        new_fan_voltage = max(0, fan_voltage - 5)

    if new_fan_voltage != fan_voltage:
        context[0].setValues(4, 4, [new_fan_voltage])
        changes["Fan Voltage"] = (fan_voltage, new_fan_voltage)

    # === Alarm Coil ===
    new_alarm = 1 if (temperature > alarm_temp or pressure > alarm_pressure) else 0
    if co[1] != new_alarm:
        context[0].setValues(1, 1, [new_alarm])
        changes["Alarm (coil 1)"] = (co[1], new_alarm)

    # === Pump ON (coil 0) ===
    if co[0] != 1:
        context[0].setValues(1, 0, [1])
        changes["Pump (coil 0)"] = (co[0], 1)

    # === Fan ON (coil 2) if fan voltage > 0 ===
    fan_on = 1 if new_fan_voltage > 0 else 0
    if co[2] != fan_on:
        context[0].setValues(1, 2, [fan_on])
        changes["Fan (coil 2)"] = (co[2], fan_on)

    for what, (old, new) in changes.items():
        logging.info(f"PLC: {what} changed from {old} to {new}")

def main():
    if not os.path.exists(JSON_FILE):
        with open(JSON_FILE, "w") as f:
            f.write(INITIAL_SENSOR_JSON)
        print(f"Created {JSON_FILE} with defaults")

    # Load, strip, write TMP
    raw = read_json_strip_comments(JSON_FILE)
    write_tmp_file(raw)

    # Setup memory and context
    context = ModbusServerContext(slaves=ModbusSlaveContext(
        co=ModbusSequentialDataBlock(0, [0]*100),
        di=ModbusSequentialDataBlock(0, [0]*100),
        hr=ModbusSequentialDataBlock(0, [0]*100),
        ir=ModbusSequentialDataBlock(0, [0]*100)
    ), single=True)

    update_modbus_memory(context, raw)

    identity = ModbusDeviceIdentification()
    identity.VendorName = "OT DEMO"
    identity.ProductName = "Modbus PLC"
    identity.ModelName = "pymodbus"
    identity.MajorMinorRevision = "1.0"

    print("Starting Modbus TCP server on port 5020...")
    from threading import Thread
    Thread(target=lambda: StartTcpServer(context=context, identity=identity, address=("0.0.0.0", 5020)), daemon=True).start()

    iteration = 0
    while True:
        iteration += 1
        if MEMORY_VIEW:
            print_snapshot(context, iteration, "MEMORY")

        if iteration % PLC_LOOP_MULTIPLIER == 0:
            new_data = read_json_strip_comments(TMP_FILE)
            update_modbus_memory(context, new_data)
            plc_logic(context)
            updated = read_modbus_memory(context)
            write_tmp_file(updated)

        time.sleep(PRINT_STATUS_CYCLE)

# Initial values in JSON (commented)
INITIAL_SENSOR_JSON = '''{
  "coils": {
    "0": 1,    # Pump ON
    "1": 0,    # Alarm OFF
    "2": 1,    # Fan ON
    "3": 0     # Emergency Stop OFF
  },
  "discrete_inputs": {
    "0": 1,    # Door Closed
    "1": 1,    # Safety OK
    "2": 1     # Fan Active
  },
  "input_registers": {
    "0": 250,  # Pump Voltage
    "1": 55,   # Temperature
    "2": 900,  # Pressure
    "3": 100,  # Throughput
    "4": 250   # Fan Voltage
  },
  "holding_registers": {
    "0": 250,  # Fan Power
    "1": 55,   # Target Temperature
    "2": 900,  # Target Pressure
    "3": 75,   # Alarm Temp Threshold
    "4": 1100, # Alarm Pressure Threshold
    "5": 1     # Mode: 1 = Run, 0 = Idle
  }
}'''

if __name__ == "__main__":
    main()
