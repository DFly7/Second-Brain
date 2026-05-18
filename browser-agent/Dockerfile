FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ARG ARCH=x86_64
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=${ARCH:+0}

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    xvfb x11vnc \
    git curl wget \
    && if [ "$ARCH" = "arm64" ]; then apt-get install -y chromium-browser; fi \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install websockify && \
    git clone --depth=1 https://github.com/novnc/noVNC.git /opt/novnc

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt && \
    if [ "$ARCH" != "arm64" ]; then playwright install chromium && playwright install-deps chromium; fi

COPY . .
RUN chmod +x start.sh

EXPOSE 6080 8001

CMD ["./start.sh"]
