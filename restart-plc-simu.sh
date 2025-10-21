pkill -9 -f 'modbus-1'
rm *.log
rm *.tmp
source venv/bin/activate
setsid ./modbus-1-field.py > /dev/null 2>&1  &
./modbus-1-plc.py

