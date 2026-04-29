FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY app.py /app/app.py

ENV HOST=0.0.0.0
ENV PORT=8099
ENV BASE_PATH=/devices
ENV API_BASE_PATH=/devices-api
ENV WIZ_LIGHT_IP=192.168.1.149
ENV XIAOMI_PLUG_IP=192.168.1.207
ENV XIAOMI_MODE=miot

EXPOSE 8099
CMD ["python", "/app/app.py"]
