#!/bin/bash

set -e

# Variablen
REPO_URL="https://github.com/Xerolux/Modbus-Tcp-Proxy.git"
BASE_DIR="/opt/Modbus-Tcp-Proxy"
INSTALL_SCRIPT="$BASE_DIR/install.sh"
SERVICE_NAME="modbus_proxy.service"
DEFAULT_CONFIG_FILE="$BASE_DIR/config.default.yaml"
CONFIG_FILE="$BASE_DIR/config.yaml"
MERGE_SCRIPT="$BASE_DIR/merge_config.py"

# Prüfen auf Debian 12 oder Ubuntu 24
check_os() {
    echo "Prüfe Betriebssystemversion..."
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        if [[ "$ID" == "debian" && "$VERSION_ID" == "12" ]] || [[ "$ID" == "ubuntu" && "$VERSION_ID" == "24.04" ]]; then
            echo "Betriebssystem unterstützt: $PRETTY_NAME"
        else
            echo "Nicht unterstütztes Betriebssystem: $PRETTY_NAME"
            echo "Dieses Skript unterstützt nur Debian 12 und Ubuntu 24."
            exit 1
        fi
    else
        echo "Konnte /etc/os-release nicht finden. Betriebssystemprüfung fehlgeschlagen."
        exit 1
    fi
}

# Funktion zur Aktualisierung und erneuten Ausführung des Skripts
update_and_execute_latest() {
    echo "Prüfe auf die neueste Version des Installationsskripts..."
    if [ -d "$BASE_DIR/.git" ]; then
        echo "Aktualisiere Repository..."
        git -C "$BASE_DIR" fetch
        git -C "$BASE_DIR" reset --hard origin/main
    else
        echo "Klone Repository..."
        git clone "$REPO_URL" "$BASE_DIR"
    fi

    # Prüfe, ob das Installationsskript aktualisiert wurde
    if [ "$(sha256sum "$INSTALL_SCRIPT" | awk '{print $1}')" != "$(git -C "$BASE_DIR" show origin/main:install.sh | sha256sum | awk '{print $1}')" ]; then
        echo "Installationsskript wurde aktualisiert. Starte erneut..."
        exec bash "$INSTALL_SCRIPT" "$@"
    fi
}

# Dienst stoppen
stop_service() {
    echo "Stoppe $SERVICE_NAME..."
    sudo systemctl stop "$SERVICE_NAME" || echo "$SERVICE_NAME läuft nicht."
}

# Dienst starten
start_service() {
    echo "Starte $SERVICE_NAME..."
    sudo systemctl start "$SERVICE_NAME"
}

# Zeige die aktuelle Version
display_version() {
    VERSION_FILE="$BASE_DIR/VERSION"
    if [ -f "$VERSION_FILE" ]; then
        echo "Aktuelle Version: $(cat $VERSION_FILE)"
    else
        echo "VERSION-Datei nicht gefunden."
    fi
}

# Konfigurationsänderungen überprüfen
check_configuration_update() {
    echo "Möchten Sie die Konfiguration nach dem Update ändern?"
    read -p "Ja [j] oder Nein [n] (Standard: n): " choice
    choice=${choice:-n}
    if [[ "$choice" == "j" || "$choice" == "J" ]]; then
        echo "Öffne Konfiguration zur Bearbeitung..."
        nano "$CONFIG_FILE"
    else
        echo "Bestehende Konfiguration wird beibehalten."
    fi
}

# Überprüfen und das Skript aktualisieren
if [ "$(basename "$0")" != "install.sh" ]; then
    cp "$0" "$INSTALL_SCRIPT"
    exec bash "$INSTALL_SCRIPT" "$@"
else
    update_and_execute_latest
fi

# Betriebssystemprüfung
check_os

# Installationsprozess starten
echo "Starte den Installationsprozess..."

# Abhängigkeiten installieren
echo "Aktualisiere System und installiere Abhängigkeiten..."
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git bc || { echo "Fehler beim Installieren der Abhängigkeiten. Beende."; exit 1; }

# Basisverzeichnis erstellen
if [ ! -d "$BASE_DIR" ]; then
    echo "Erstelle Basisverzeichnis $BASE_DIR..."
    sudo mkdir -p "$BASE_DIR"
    sudo chown $USER:$USER "$BASE_DIR"
else
    echo "Basisverzeichnis $BASE_DIR existiert bereits."
fi

# Repository klonen oder aktualisieren
if [ -d "$BASE_DIR/.git" ]; then
    echo "Aktualisiere Repository..."
    git -C "$BASE_DIR" fetch && git -C "$BASE_DIR" reset --hard origin/main || { echo "Fehler beim Aktualisieren des Repositories. Beende."; exit 1; }
else
    echo "Klone Repository von $REPO_URL..."
    git clone "$REPO_URL" "$BASE_DIR" || { echo "Fehler beim Klonen des Repositories. Beende."; exit 1; }
fi

# Version anzeigen
display_version

# Dienst vor Aktualisierung stoppen
stop_service

# Python-Version prüfen
python3 -c "import sys; assert sys.version_info >= (3, 7), 'Python 3.7 oder neuer ist erforderlich.'" || { echo "Python-Version wird nicht unterstützt. Beende."; exit 1; }

# Virtuelle Umgebung erstellen oder aktivieren
VENV_DIR="$BASE_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "Erstelle virtuelle Umgebung..."
    python3 -m venv "$VENV_DIR" || { echo "Fehler beim Erstellen der virtuellen Umgebung. Beende."; exit 1; }
else
    echo "Virtuelle Umgebung existiert bereits."
fi
source "$VENV_DIR/bin/activate"

# Python-Abhängigkeiten installieren
REQ_FILE="$BASE_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "requirements.txt nicht gefunden. Beende."
    deactivate
    exit 1
fi
echo "Installiere Python-Abhängigkeiten..."
pip install -r "$REQ_FILE" || { echo "Fehler beim Installieren der Python-Abhängigkeiten. Beende."; deactivate; exit 1; }

# Konfigurationsdatei prüfen und zusammenführen
if [ -f "$CONFIG_FILE" ]; then
    echo "Bestehende config.yaml gefunden. Füge neue Felder aus config.default.yaml hinzu..."
    python3 "$MERGE_SCRIPT"
else
    echo "Erstelle neue Konfigurationsdatei aus config.default.yaml..."
    cp "$DEFAULT_CONFIG_FILE" "$CONFIG_FILE"
fi

# Konfiguration überprüfen und ändern
check_configuration_update

# Systemd-Service-Datei aktualisieren
echo "Aktualisiere systemd-Service-Datei..."
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"
sudo bash -c "cat << EOF > $SERVICE_FILE
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=$VENV_DIR/bin/python3 $BASE_DIR/modbus_tcp_proxy.py
WorkingDirectory=$BASE_DIR
Restart=always
User=$USER
Environment=\"PYTHONUNBUFFERED=1\"

[Install]
WantedBy=multi-user.target
EOF"

sudo systemctl daemon-reload

# Dienst starten
start_service

# Version anzeigen
echo "Installation abgeschlossen!"
display_version
echo "Verwende 'sudo systemctl restart $SERVICE_NAME', um Konfigurationsänderungen anzuwenden."
