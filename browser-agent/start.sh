#!/bin/bash
set -e

Xvfb :99 -screen 0 1280x800x24 &
sleep 1

x11vnc -display :99 -forever -nopw -listen localhost -port 5900 &
sleep 1

websockify --web=/opt/novnc 0.0.0.0:6080 localhost:5900 &
sleep 1

exec uvicorn main:app --host 0.0.0.0 --port 8001
