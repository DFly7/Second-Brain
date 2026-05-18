#!/bin/bash
set -e

Xvfb :99 -screen 0 1280x800x24 &
# Wait up to 10s for Xvfb
for i in $(seq 1 20); do xdpyinfo -display :99 >/dev/null 2>&1 && break; sleep 0.5; done

x11vnc -display :99 -forever -nopw -rfbport 5900 &
# Wait up to 10s for x11vnc
for i in $(seq 1 20); do nc -z localhost 5900 2>/dev/null && break; sleep 0.5; done

websockify --web=/opt/novnc 0.0.0.0:6080 localhost:5900 &
sleep 1

exec uvicorn main:app --host 0.0.0.0 --port 8001
