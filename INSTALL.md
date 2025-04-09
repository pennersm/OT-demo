# Installation Instructions

This project is compatible with **Python 3.10+** and tested on **Ubuntu 22.04 and 24.04 LTS**.

## 1. Check Python Installation

Ubuntu 24.04 ships with Python 3 pre-installed.

```
python3 --version
```

Expected output:
```
Python 3.10.x
```

If not installed, run:
```
sudo apt update
sudo apt install python3 -y
```

---

## 2. Ensure `pip` is Installed

Check if `pip3` is available:

```
pip3 --version
```

To install or update `pip`:
```
sudo apt install python3-pip -y
```

---

## 3. Install Python Requirements

Create a virtual environment (recommended for managed systems or development):

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

To install system-wide (if allowed and preferred):

```
sudo pip3 install -r requirements.txt
```

---

## 4. Run the Simulation Environment

Make all `.py` scripts executable (once):

```
chmod +x *.py
```

Start components in separate terminals:

**Terminal 1 – Start the PLC Server**
```
./modbus-server.py
```

**Terminal 2 – Start the HMI Client**
```
./hmi-client.py
```

**Terminal 3 – Start the Reality Loop**
```
./reality-loop.py &
tail -f plc_reality.log
```

---

## 5. File Structure

- `requirements.txt`: Declares the exact dependencies
- `OTdemo.conf`: Common configuration file
- `modbus-server.py`: Starts Modbus-based PLC controller
- `hmi-client.py`: Displays current memory (optional)
- `reality-loop.py`: Simulates physical changes over time
- `plc_server.log` / `plc_reality.log`: Log files for debugging

