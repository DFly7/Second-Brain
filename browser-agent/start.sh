#!/bin/bash
set -e

Xvfb :99 -screen 0 1280x800x24 &
# Wait until Xvfb is accepting connections
until xdpyinfo -display :99 >/dev/null 2>&1; do sleep 0.5; done

x11vnc -display :99 -forever -nopw -port 5900 &
# Wait until x11vnc is listening on 5900
until nc -z localhost 5900 2>/dev/null; do sleep 0.5; done

websockify --web=/opt/novnc 0.0.0.0:6080 localhost:5900 &
sleep 1

exec uvicorn main:app --host 0.0.0.0 --port 8001
