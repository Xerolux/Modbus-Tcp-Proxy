#!/bin/bash

set -e  # Beendet das Script sofort, wenn ein Befehl fehlschlägt

# Variablen
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
BASE_DIR="/opt/Modbus-Tcp-Proxy"
CONFIG_DIR="/etc/Modbus-Tcp-Proxy"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
SERVICE_NAME="modbus_proxy.service"
SERVICE_USER="modbus_proxy"

# Überprüfung der Konfigurationsdatei
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Fehler: Konfigurationsdatei nicht gefunden unter $CONFIG_FILE."
    echo "Bitte erstelle die Datei 'config.yaml' bevor du fortfährst. Ein Beispiel findest du im Repository oder in der Dokumentation."
    exit 1
fi

# Installation der Abhängigkeiten
echo "Installiere Abhängigkeiten..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git

# Erstellen eines dedizierten Systembenutzers für den Dienst, falls er nicht existiert
if ! id -u "$SERVICE_USER" > /dev/null 2>&1; then
    echo "Erstelle Systembenutzer '$SERVICE_USER'..."
    sudo useradd -r -s /bin/false "$SERVICE_USER"
fi

# Klonen oder Aktualisieren des Repositories mit sudo
if [ -d "$BASE_DIR/.git" ]; then
    echo "Aktualisiere Repository..."
    sudo git -C "$BASE_DIR" pull || { echo "Fehler beim Aktualisieren des Repositories."; exit 1; }
else
    echo "Klone Repository..."
    sudo git clone "$REPO_URL" "$BASE_DIR" || { echo "Fehler beim Klonen des Repositories."; exit 1; }
fi

# Einrichtung der Python-Virtual-Umgebung mit sudo
if [ -d "$BASE_DIR/venv" ]; then
    echo "Aktualisiere Abhängigkeiten..."
    sudo "$BASE_DIR/venv/bin/pip" install -r "$BASE_DIR/requirements.txt" --upgrade
else
    echo "Erstelle virtuelle Umgebung..."
    sudo python3 -m venv "$BASE_DIR/venv"
    sudo "$BASE_DIR/venv/bin/pip" install -r "$BASE_DIR/requirements.txt"
fi

# Stoppen des Dienstes, falls er bereits läuft
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Stoppe bestehenden Dienst..."
    sudo systemctl stop "$SERVICE_NAME"
fi

# Erstellen der systemd-Dienstdatei
echo "Erstelle systemd-Dienst..."
sudo tee /etc/systemd/system/$SERVICE_NAME > /dev/null <<EOF
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=$BASE_DIR/venv/bin/python3 $BASE_DIR/modbus_tcp_proxy.py --config $CONFIG_FILE
WorkingDirectory=$BASE_DIR
Restart=always
User=$SERVICE_USER
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

# Systemd neu laden, Dienst aktivieren und starten
echo "Starte und aktiviere Dienst..."
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl start "$SERVICE_NAME"

# Überprüfen, ob der Dienst erfolgreich gestartet wurde
if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "Dienst erfolgreich gestartet."
else
    echo "Fehler beim Starten des Dienstes. Überprüfe die Logs mit 'journalctl -u $SERVICE_NAME'."
    exit 1
fi

# Erfolgsmeldung
echo "Installation erfolgreich abgeschlossen!"
echo "Dienst: $SERVICE_NAME läuft."
echo "Bearbeite die Konfiguration unter: $CONFIG_FILE falls nötig."
