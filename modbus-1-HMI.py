#!/usr/bin/env python3
import sys, time, json, re, os, select, threading
from pymodbus.client import ModbusTcpClient

CONFIG_FILE = "OTdemo.conf"
SECTION = "modbus-plc1"

def strip_comments_and_parse(filepath):
    with open(filepath, 'r') as f:
        lines = f.readlines()
    clean = [re.sub(r'#.*$', '', line).strip() for line in lines if line.strip() and not line.strip().startswith('#')]
    return json.loads('\n'.join(clean))

conf = strip_comments_and_parse(CONFIG_FILE)[SECTION]
SERVER_IP = conf["PLC_SERVER_IP"]
SERVER_PORT = int(conf["PLC_SERVER_PORT"])
POLL_INTERVAL = conf["HMI_POLL_INTERVAL"]

# === Color Codes ===
RED = '\033[91m'; GREEN = '\033[92m'; YELLOW = '\033[93m'
BLUE = '\033[94m'; CYAN = '\033[96m'; WHITE = '\033[97m'
RESET = '\033[0m'

LABELS = {
    'coils': {
        0: "Pump (coil 0)", 1: "Alarm (coil 1)", 2: "Fan (coil 2)",
        3: "Heating (coil 3)", 4: "Emergency Stop (coil 4)", 5: "Relief Valve (coil 5)"
    },
    'discrete_inputs': {
        0: "Door Closed (di 0)", 1: "Safety OK (di 1)",
        2: "Fan Active (di 2)", 3: "Heating Active (di 3)"
    },
    'input_registers': {
        0: "Pump Voltage (ir 0)", 1: "Temperature (ir 1)", 2: "Pressure (ir 2)",
        3: "Throughput (ir 3)", 4: "Fan RPM (ir 4)", 5: "Heater Power (ir 5)"
    },
    'holding_registers': {
        0: "Target Temp (hr 0)", 1: "Target Pressure (hr 1)",
        2: "Alarm Temp Thresh (hr 2)", 3: "Alarm Pressure Thresh (hr 3)",
        4: "Mode (hr 4)", 5: "Pump Ctrl Cmd (hr 5)",
        6: "Relief Threshold (hr 6)", 7: "Relief Bleed Rate (hr 7)"
    }
}

def fmt_bool(val):
    return f"{GREEN}ON{RESET}" if val == 1 else f"{RED}OFF{RESET}" if val == 0 else f"{RED}unknown{RESET}"

def fmt_val(val):
    return f"{YELLOW}{val}{RESET}" if isinstance(val, int) else f"{RED}unknown{RESET}"

def int16_signed(val):
    return val - 0x10000 if val >= 0x8000 else val

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

def print_snapshot(data, local_delta, mode, connected, ip):
    print("\033[2J\033[H", end="")  # Clear screen
    status = f"Connected to {ip}" if connected else "Unconnected"
    print(f"{CYAN}{'='*60}")
    print(f"                  HMI STATUS - {status} ")
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
        if i == 5:
            signed_val = int16_signed(val) if isinstance(val, int) else val
            if mode == 2 and local_delta != 0:
                print(f"  - {LABELS['holding_registers'][i]:<35}: {YELLOW}{local_delta} (pending){RESET}")
            else:
                print(f"  - {LABELS['holding_registers'][i]:<35}: {fmt_val(signed_val)}")
        elif i in LABELS['holding_registers']:
            print(f"  - {LABELS['holding_registers'][i]:<35}: {fmt_val(val)}")
    print(f"{CYAN}{'='*60}{RESET}")

    print(f"{WHITE}Current Mode: {'Manual' if mode == 2 else 'Auto' if mode == 1 else 'Idle'}{RESET}")
    print(f"{WHITE}Commands: [m = toggle mode] [+/- = adjust pump delta] [s = send delta] [ENTER = refresh]{RESET}")
    print(f"{WHITE}Command > {RESET}", end="", flush=True)

def hmi_loop(client):
    pump_delta = 0
    while True:
        data = read_modbus(client)
        mode = data["holding_registers"][4]
        print_snapshot(data, pump_delta, mode, connected=True, ip=SERVER_IP)

        rlist, _, _ = select.select([sys.stdin], [], [], POLL_INTERVAL)
        if rlist:
            cmd = sys.stdin.readline().strip().lower()
            if cmd == "m":
                new_mode = 2 if mode == 1 else 1
                client.write_register(4, new_mode)
            elif cmd == "+":
                pump_delta += 20
            elif cmd == "-":
                pump_delta -= 20
            elif cmd == "s":
                signed_16bit = pump_delta & 0xFFFF
                client.write_register(5, signed_16bit)
                print(f"{YELLOW}\nSent delta {pump_delta} to HR[5]. Remaining in MANUAL mode.{RESET}")
                pump_delta = 0
                time.sleep(0.5)
            elif cmd == "":
                pass
            else:
                print(f"{YELLOW}\nUnknown or unsupported command.{RESET}")
                time.sleep(0.8)

def main():
    client = ModbusTcpClient(SERVER_IP, port=SERVER_PORT)
    print(f"Connecting to Modbus server at {SERVER_IP}:{SERVER_PORT} ...")

    original_stderr = sys.stderr
    with open(os.devnull, 'w') as fnull:
        sys.stderr = fnull
        while not client.connect():
            print("Waiting...")
            time.sleep(1)
        sys.stderr = original_stderr

    print("Connected to Modbus server.")
    try:
        hmi_loop(client)
    except KeyboardInterrupt:
        print(f"{YELLOW}\nExiting HMI viewer.{RESET}")
    finally:
        client.close()

if __name__ == "__main__":
    main()
