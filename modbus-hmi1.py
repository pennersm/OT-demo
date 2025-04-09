#!/usr/bin/env python3
import sys
import time
import json
import re
from pymodbus.client import ModbusTcpClient

# === CONFIGURATION ===
CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"

def strip_comments_and_parse(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    clean = [re.sub(r'#.*$', '', line).strip() for line in lines if line.strip() and not line.strip().startswith('#')]
    return json.loads('\n'.join(clean))

conf = strip_comments_and_parse(CONFIG_FILE)[SECTION]
SERVER_IP = conf["PLC_SERVER_IP"]
SERVER_PORT = conf["PLC_SERVER_PORT"]
POLL_INTERVAL = conf["HMI_POLL_INTERVAL"]

# === Color Codes ===
RED    = '\033[91m'
GREEN  = '\033[92m'
YELLOW = '\033[93m'
BLUE   = '\033[94m'
CYAN   = '\033[96m'
WHITE  = '\033[97m'
RESET  = '\033[0m'

# === Labels ===
LABELS = {
    'coils': {
        0: "Pump (coil 0)",
        1: "Alarm (coil 1)",
        2: "Fan (coil 2)"
    },
    'discrete_inputs': {
        0: "Door Closed (di 0)",
        1: "Safety OK (di 1)",
        2: "Fan Active (di 2)"
    },
    'input_registers': {
        0: "Pump Voltage (ir 0)",
        1: "Temperature (ir 1)",
        2: "Pressure (ir 2)",
        3: "Throughput (ir 3)"
    },
    'holding_registers': {
        0: "Fan Voltage (hr 0)",
        1: "Target Temp (hr 1)",
        2: "Target Pressure (hr 2)",
        3: "Temp Alarm Threshold (hr 3)",
        4: "Pressure Alarm Threshold (hr 4)",
        5: "Mode (hr 5)"
    }
}

def fmt_bool(val):
    if val == 1:
        return f"{GREEN}ON{RESET}"
    elif val == 0:
        return f"{RED}OFF{RESET}"
    else:
        return f"{RED}unknown{RESET}"

def fmt_val(val):
    return f"{YELLOW}{val}{RESET}" if isinstance(val, int) else f"{RED}unknown{RESET}"

def read_modbus(client):
    try:
        return {
            "coils": read_bits(client.read_coils(0, 10), 10),
            "discrete_inputs": read_bits(client.read_discrete_inputs(0, 10), 10),
            "input_registers": read_regs(client.read_input_registers(0, 10), 10),
            "holding_registers": read_regs(client.read_holding_registers(0, 10), 10)
        }
    except Exception:
        return unknown_snapshot()

def read_bits(resp, count):
    return resp.bits[:count] if resp and not resp.isError() else ["unknown"] * count

def read_regs(resp, count):
    return resp.registers[:count] if resp and not resp.isError() else ["unknown"] * count

def unknown_snapshot():
    return {
        "coils": ["unknown"] * 10,
        "discrete_inputs": ["unknown"] * 10,
        "input_registers": ["unknown"] * 10,
        "holding_registers": ["unknown"] * 10
    }

def print_snapshot(data):
    print("\033[2J\033[H", end="")
    print(f"{CYAN}{'='*60}")
    print("                  HMI STATUS DISPLAY")
    print(f"{'='*60}{RESET}\n")

    print(f"{WHITE}» COILS (Actuators):{RESET}")
    for i, val in enumerate(data["coils"]):
        if i in LABELS['coils']:
            print(f"  - {LABELS['coils'][i]:<35}: {fmt_bool(val)}")
    print()

    print(f"{WHITE}» DISCRETE INPUTS (Sensors):{RESET}")
    for i, val in enumerate(data["discrete_inputs"]):
        if i in LABELS['discrete_inputs']:
            print(f"  - {LABELS['discrete_inputs'][i]:<35}: {fmt_bool(val)}")
    print()

    print(f"{WHITE}» INPUT REGISTERS (Field Data):{RESET}")
    for i, val in enumerate(data["input_registers"]):
        if i in LABELS['input_registers']:
            print(f"  - {LABELS['input_registers'][i]:<35}: {fmt_val(val)}")
    print()

    print(f"{WHITE}» HOLDING REGISTERS (Config):{RESET}")
    for i, val in enumerate(data["holding_registers"]):
        if i in LABELS['holding_registers']:
            print(f"  - {LABELS['holding_registers'][i]:<35}: {fmt_val(val)}")
    print(f"{CYAN}{'='*60}{RESET}")

def main():
    client = ModbusTcpClient(SERVER_IP, port=SERVER_PORT)
    try:
        while True:
            if client.connect():
                data = read_modbus(client)
                print_snapshot(data)
                client.close()
            else:
                print_snapshot(unknown_snapshot())
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        print(f"{YELLOW}\nExiting HMI viewer.{RESET}")

if __name__ == "__main__":
    main()
