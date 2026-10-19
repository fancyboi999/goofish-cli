FROM mcr.microsoft.com/playwright/python:v1.58.0-noble@sha256:678457c4c323b981d8b4befc57b95366bb1bb6aa30057b1269f6b171e8d9975a
USER root
RUN apt-get update && apt-get install -y --no-install-recommends fluxbox x11vnc novnc websockify x11-utils fonts-noto-cjk nodejs && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/requirements.txt
RUN python -m venv --without-pip /opt/venv && pip --python /opt/venv/bin/python install --no-cache-dir -r /opt/requirements.txt playwright==1.58.0 hatchling
COPY package /opt/goofish
RUN pip --python /opt/venv/bin/python install --no-deps --no-build-isolation /opt/goofish
COPY entrypoint.sh /opt/entrypoint.sh
RUN chmod 755 /opt/entrypoint.sh && mkdir -p /home/pwuser/.goofish-cli && chown pwuser:pwuser /home/pwuser/.goofish-cli && chmod 700 /home/pwuser/.goofish-cli
USER pwuser
ENV HOME=/home/pwuser PATH=/opt/venv/bin:$PATH DISPLAY=:1 GOOFISH_DESKTOP_SANDBOX=1 GOOFISH_HEADLESS=0 GOOFISH_NO_CHROME_BOOTSTRAP=1
WORKDIR /home/pwuser
ENTRYPOINT ["/opt/entrypoint.sh"]
