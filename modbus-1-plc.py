#!/usr/bin/env python3
import json, time, os, re, logging
from pymodbus.server import StartTcpServer
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.datastore.store import ModbusSequentialDataBlock
from pymodbus.device import ModbusDeviceIdentification
from threading import Thread

CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"
with open(CONFIG_FILE) as f:
    conf = json.load(f)[SECTION]

TMP_FILE = conf["TMP_FILE"]
LOG_FILE = conf["PLC_LOG_FILE"]
PLC_SERVER_PORT = int(conf["PLC_SERVER_PORT"])
PRINT_STATUS_CYCLE = int(conf["PRINT_STATUS_CYCLE"])
PLC_LOOP_MULTIPLIER = int(conf["PLC_LOOP_MULTIPLIER"])
MEMORY_VIEW = conf["MEMORY_VIEW"]

logging.basicConfig(filename=LOG_FILE, filemode='w', level=logging.INFO,
    format='%(asctime)s - %(message)s')

LABELS = {
    "coils": {
        0: "Pump", 1: "Alarm", 2: "Fan", 3: "Heating", 4: "Emergency Stop", 5: "Pressure Relief Valve"
    },
    "discrete_inputs": {
        0: "Door Closed", 1: "Safety OK", 2: "Fan Active", 3: "Heating Active"
    },
    "input_registers": {
        0: "Pump Voltage", 1: "Temperature", 2: "Pressure", 3: "Throughput",
        4: "Fan RPM", 5: "Heater Power"
    },
    "holding_registers": {
        0: "Target Temp", 1: "Target Pressure", 2: "Alarm Temp",
        3: "Alarm Pressure", 4: "Mode", 5: "Pump Delta",
        6: "Relief Threshold", 7: "Bleed Rate"
    }
}

def clamp(val, minval, maxval):
    return max(minval, min(val, maxval))

def strip_comments(text):
    return json.loads('\n'.join(
        [re.sub(r'#.*$', '', l).strip() for l in text.splitlines()
         if l.strip() and not l.strip().startswith('#')]
    ))

def read_json_strip_comments(filepath):
    with open(filepath) as f:
        return strip_comments(f.read())

def write_tmp_file_filtered(context):
    result = {}
    for name, fc in [("coils", 1), ("discrete_inputs", 2),
                     ("holding_registers", 3), ("input_registers", 4)]:
        result[name] = {}
        for i in LABELS[name]:
            if name == "holding_registers" and i == 4:
                continue  # Keep mode internal
            result[name][str(i)] = context[0].getValues(fc, i, 1)[0]
    with open(TMP_FILE, "w") as f:
        json.dump(result, f, indent=2)

def update_modbus_memory(context, data):
    # Apply discrete_inputs (read-only from the PLC point of view)
    for k, v in data.get("discrete_inputs", {}).items():
        try:
            idx = int(k)
            context[0].setValues(2, idx, [1 if int(v) else 0])
        except Exception:
            # ignore bad entries but log if you want
            pass

    # Apply input_registers (sensor-like values coming from the field)
    for k, v in data.get("input_registers", {}).items():
        try:
            idx = int(k)
            context[0].setValues(4, idx, [int(v)])
        except Exception:
            pass

def print_snapshot(context, iteration):
    def b(v): return "ON" if v == 1 else "OFF" if v == 0 else "?"
    co = context[0].getValues(1, 0, 10)
    di = context[0].getValues(2, 0, 10)
    ir = context[0].getValues(4, 0, 10)
    hr = context[0].getValues(3, 0, 10)
    mode = hr[4]

    print("\033[H\033[J", end="")
    print(f"======== MEMORY VIEW — PLC STATUS ITERATION: {iteration} ========")
    print(f"MODE: {'MANUAL' if mode == 2 else 'AUTO' if mode == 1 else 'IDLE'} (HR[4] = {mode})\n")
    print("COILS:")
    for i in LABELS["coils"]:
        print(f"  - {LABELS['coils'][i]:<30}: {b(co[i])}")
    print("\nDISCRETE INPUTS:")
    for i in LABELS["discrete_inputs"]:
        print(f"  - {LABELS['discrete_inputs'][i]:<30}: {b(di[i])}")
    print("\nINPUT REGISTERS:")
    for i in LABELS["input_registers"]:
        print(f"  - {LABELS['input_registers'][i]:<30}: {ir[i]}")
    print("\nHOLDING REGISTERS:")
    for i in LABELS["holding_registers"]:
        print(f"  - {LABELS['holding_registers'][i]:<30}: {hr[i]}")
    print("=" * 60)

def int16_signed(val):
    return val - 0x10000 if val >= 0x8000 else val

last_mode = None

def plc_logic(context):
    global last_mode
    ir = context[0].getValues(4, 0, 10)
    hr = context[0].getValues(3, 0, 10)
    co = context[0].getValues(1, 0, 10)
    changes = []

    pv, temp, press, throughput, rpm, heater = ir[:6]
    target_temp, target_press, alarm_temp, alarm_press, mode, delta = hr[:6]
    relief_thresh = hr[6] if len(hr) > 6 else 1250
    bleed_rate = hr[7] if len(hr) > 7 else 25

    if mode != last_mode:
        logging.info(f"PLC: Mode changed from {last_mode} to {mode}")
        last_mode = mode

    if co[4] == 1:
        context[0].setValues(4, 0, [0])
        context[0].setValues(4, 4, [0])
        context[0].setValues(4, 5, [0])
        logging.warning("Emergency stop — pump, fan and heater OFF")
        return

    if mode == 0:
        return

    context[0].setValues(1, 0, [1])  # Pump ON

    if mode == 2:  # MANUAL
        signed_delta = int16_signed(delta)
        if signed_delta != 0:
            current_pv = context[0].getValues(4, 0, 1)[0]
            new_pv = clamp(current_pv + signed_delta, 0, 1000)
            context[0].setValues(4, 0, [new_pv])  # Update IR[0]
            context[0].setValues(3, 5, [0])       # Reset HR[5]
            changes.append(f"PumpVoltage(manual): {current_pv} + {signed_delta} -> {new_pv}")

    elif mode == 1:  # AUTO
        TARGET_THROUGHPUT = 100
        VOLTAGE_FLOOR = 200

        if throughput < 20:
            required_voltage = 250
        else:
            penalty_factor = max(0.0, (temp - 70) / 100)
            try:
                required_voltage = int(TARGET_THROUGHPUT / (1 - penalty_factor))
            except ZeroDivisionError:
                required_voltage = 1000

        new_pv = clamp(required_voltage, VOLTAGE_FLOOR, 1000)
        if new_pv != pv:
            context[0].setValues(4, 0, [new_pv])
            changes.append(f"PumpVoltage(static): {pv} -> {new_pv}")

        drpm = int((temp - target_temp) * 2.5)
        drpm = clamp(drpm, -80, 80)
        new_rpm = clamp(rpm + drpm, 0, 1000)
        if new_rpm != rpm:
            context[0].setValues(4, 4, [new_rpm])
            changes.append(f"FanRPM(adj): {rpm} -> {new_rpm}")

        if temp < target_temp - 1:
            heater_power = clamp(int((target_temp - temp) * 4), 0, 300)
            context[0].setValues(1, 3, [1])
            context[0].setValues(4, 5, [heater_power])
            changes.append(f"Heater ON: {heater_power}")
        elif temp > target_temp + 2:
            context[0].setValues(1, 3, [0])
            context[0].setValues(4, 5, [0])
            changes.append("Heater OFF")

        # Pressure relief valve logic (Option 3)
        if press > relief_thresh:
            context[0].setValues(1, 5, [1])  # Open valve
            reduced_pressure = clamp(press - bleed_rate, 0, 1500)
            context[0].setValues(4, 2, [reduced_pressure])
            changes.append(f"ReliefValve OPEN: pressure {press} -> {reduced_pressure}")
        else:
            context[0].setValues(1, 5, [0])  # Close valve

    alarm = 1 if temp > alarm_temp or press > alarm_press else 0
    if co[1] != alarm:
        context[0].setValues(1, 1, [alarm])
        changes.append(f"Alarm: {co[1]} -> {alarm}")

    fan_rpm = context[0].getValues(4, 4, 1)[0]
    fan_on = 1 if fan_rpm > 0 else 0
    if co[2] != fan_on:
        context[0].setValues(1, 2, [fan_on])
        changes.append(f"Fan: {co[2]} -> {fan_on}")

    co_vals = context[0].getValues(1, 0, 6)
    ir_vals = context[0].getValues(4, 0, 6)
    hr_vals = context[0].getValues(3, 0, 8)
    logging.info(f"PLC: COILS: {co_vals}, IR: {ir_vals}, HR: {hr_vals}")
    for c in changes:
        logging.info("PLC: " + c)

def main():
    print("PLC waiting for sensors.tmp...")
    while not os.path.exists(TMP_FILE):
        time.sleep(1)

    data = read_json_strip_comments(TMP_FILE)
    mode = int(data.get("holding_registers", {}).get("4", 0))

    context = ModbusServerContext(slaves=ModbusSlaveContext(
        co=ModbusSequentialDataBlock(0, [0]*100),
        di=ModbusSequentialDataBlock(0, [0]*100),
        hr=ModbusSequentialDataBlock(0, [0]*100),
        ir=ModbusSequentialDataBlock(0, [0]*100)
    ), single=True)

    update_modbus_memory(context, data)
    context[0].setValues(3, 4, [mode])  # Set initial mode

    Thread(target=lambda: StartTcpServer(
        context=context, identity=ModbusDeviceIdentification(),
        address=("0.0.0.0", PLC_SERVER_PORT)), daemon=True).start()

    iteration = 0
    while True:
        iteration += 1

        try:
            new_data = read_json_strip_comments(TMP_FILE)
            update_modbus_memory(context, new_data)
        except Exception as e:
            logging.warning(f"Memory update error: {e}")

        if iteration % PLC_LOOP_MULTIPLIER == 0:
            try:
                plc_logic(context)
                write_tmp_file_filtered(context)
            except Exception as e:
                logging.warning(f"PLC loop error: {e}")

        if MEMORY_VIEW:
            print_snapshot(context, iteration)

        time.sleep(PRINT_STATUS_CYCLE)

if __name__ == "__main__":
    main()

