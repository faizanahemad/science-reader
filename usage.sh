#!/bin/bash

while true; do
    echo "---------  Date: $(date) --------- " >> usage.log
    echo "CPU usage:" >> usage.log
    top -o %CPU -bn1 | head -n 12 | tail -n 6 >> usage.log
    echo "Memory usage:" >> usage.log
    top -o %MEM -bn1 | head -n 12 | tail -n 6 >> usage.log
    sleep 30
done