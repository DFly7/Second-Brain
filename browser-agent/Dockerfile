FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DISPLAY=:99
ARG ARCH=x86_64

RUN apt-get update && apt-get install -y \
    python3 python3-pip \
    xvfb x11vnc x11-utils netcat-openbsd \
    git curl wget \
    fonts-liberation fonts-noto-core fonts-noto-cjk fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install websockify && \
    git clone --depth=1 https://github.com/novnc/noVNC.git /opt/novnc

WORKDIR /app
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# x86_64: install real Google Chrome (best fingerprint). arm64: Chrome has no
# Linux arm64 build, so use patchright's patched Chromium instead.
RUN if [ "$ARCH" = "arm64" ]; then \
        patchright install --with-deps chromium ; \
    else \
        patchright install --with-deps chrome ; \
    fi

COPY . .
RUN chmod +x start.sh

EXPOSE 6080 8001

CMD ["./start.sh"]
