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
VERSION_FILE="$BASE_DIR/VERSION"

# Funktion: Lokale IP-Adresse ermitteln
get_local_ip() {
    local_ip=$(hostname -I | awk '{print $1}')
    if [[ -z "$local_ip" ]]; then
        echo "Konnte keine lokale IP-Adresse ermitteln. Stelle sicher, dass das Netzwerk funktioniert."
        exit 1
    fi
    echo "$local_ip"
}

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

# Dienst stoppen
stop_service() {
    echo "Stoppe $SERVICE_NAME..."
    sudo systemctl stop "$SERVICE_NAME" || echo "$SERVICE_NAME läuft nicht."
}

# Dienst starten oder neu starten
restart_service() {
    echo "Starte $SERVICE_NAME neu..."
    sudo systemctl daemon-reload
    sudo systemctl restart "$SERVICE_NAME"
}

# Zeige die aktuelle Version und Host-Info
display_info() {
    local version
    local proxy_port
    local_ip=$(get_local_ip)

    version=$(cat "$VERSION_FILE")
    proxy_port=$(grep -Po '(?<=ServerPort: ).*' "$CONFIG_FILE" | head -1)

    echo "Update / Start / Install erfolgreich!"
    echo "Version: $version"
    echo "Proxy ist erreichbar unter: ${local_ip}:${proxy_port}"
}

# Konfigurationsmenü anzeigen und bearbeiten
config_menu() {
    echo "Prüfe Konfigurationsdatei..."

    # Standardwerte laden, falls keine Konfiguration vorhanden ist
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "Keine Konfiguration gefunden. Erstelle neue Konfigurationsdatei basierend auf den Standardwerten..."
        cp "$DEFAULT_CONFIG_FILE" "$CONFIG_FILE"
    fi

    # Aktuelle Konfiguration einlesen
    local current_config
    current_config=$(cat "$CONFIG_FILE")

    echo "Aktuelle Konfiguration:"
    echo "--------------------------------"
    echo "$current_config"
    echo "--------------------------------"

    # Benutzer auffordern, die Werte zu übernehmen oder anzupassen
    echo "Möchtest du die aktuelle Konfiguration übernehmen? (j/n)"
    read -r response
    if [[ "$response" =~ ^[nN]$ ]]; then
        echo "Öffne Konfigurationseditor..."
        nano "$CONFIG_FILE"
    else
        echo "Die aktuelle Konfiguration wird übernommen."
    fi

    # Prüfung, ob die Konfigurationsstruktur korrekt ist
    local required_keys=("Proxy" "ModbusServer" "Logging" "version")
    for key in "${required_keys[@]}"; do
        if ! grep -q "$key:" "$CONFIG_FILE"; then
            echo "Fehler: Schlüssel '$key' fehlt in $CONFIG_FILE. Beende."
            exit 1
        fi
    done
}

# Überprüfen und das Skript aktualisieren
update_and_execute_latest() {
    if [ "${SKIP_UPDATE_CHECK:-0}" -eq 1 ]; then
        return  # Update-Check überspringen, wenn bereits geprüft
    fi

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
    local current_hash new_hash
    current_hash=$(sha256sum "$INSTALL_SCRIPT" | awk '{print $1}')
    new_hash=$(git -C "$BASE_DIR" show origin/main:install.sh | sha256sum | awk '{print $1}')

    if [ "$current_hash" != "$new_hash" ]; then
        echo "Installationsskript wurde aktualisiert. Starte die neue Version..."
        SKIP_UPDATE_CHECK=1 exec bash "$INSTALL_SCRIPT" "$@"
    fi
}

# Betriebssystemprüfung
check_os

# Überprüfen und das Skript aktualisieren
update_and_execute_latest

# Installationsprozess starten
echo "Starte den Installationsprozess..."

# Abhängigkeiten installieren
sudo apt update && sudo apt install -y python3 python3-pip python3-venv git bc nano || { echo "Fehler beim Installieren der Abhängigkeiten. Beende."; exit 1; }

# Basisverzeichnis erstellen
if [ ! -d "$BASE_DIR" ]; then
    sudo mkdir -p "$BASE_DIR"
    sudo chown $USER:$USER "$BASE_DIR"
fi

# Python-Abhängigkeiten installieren
VENV_DIR="$BASE_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"

REQ_FILE="$BASE_DIR/requirements.txt"
if [ ! -f "$REQ_FILE" ]; then
    echo "requirements.txt nicht gefunden. Beende."
    exit 1
fi
pip install -r "$REQ_FILE"

# Konfigurationsmenü aufrufen
config_menu

# Systemd-Service-Datei erstellen
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
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF"

# Dienst starten
restart_service

# Version und Hostinformationen anzeigen
display_info

echo "Systemname: $(hostname)"
