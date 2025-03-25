FROM python:3.11-slim

# Metadaten
LABEL maintainer="Basti <basti@example.com>"
LABEL version="1.0"

# Arbeitsverzeichnis
WORKDIR /app

# Systempakete und Python-Dependencies installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App-Dateien kopieren
COPY modbus_tcp_proxy.py .
COPY config.yaml /etc/Modbus-Tcp-Proxy/config.yaml

# Port freigeben
EXPOSE 502

# Startkommando
CMD ["python", "modbus_tcp_proxy.py", "--config", "/etc/Modbus-Tcp-Proxy/config.yaml"]
