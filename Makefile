APP_NAME = Modbus-Tcp-Proxy
BASE_DIR = /opt/$(APP_NAME)
CONFIG_DIR = /etc/$(APP_NAME)
CONFIG = $(CONFIG_DIR)/config.yaml
VENV = $(BASE_DIR)/venv
PYTHON = $(VENV)/bin/python3
SERVICE = modbus_proxy.service

.PHONY: help install update start stop restart status logs backup-config uninstall

help:
	@echo ""
	@echo "Verfügbare Befehle:"
	@echo "  make install         - Installiert alles und richtet den Dienst ein"
	@echo "  make update          - Holt neueste Version & aktualisiert Abhängigkeiten"
	@echo "  make start           - Startet den systemd-Dienst"
	@echo "  make stop            - Stoppt den Dienst"
	@echo "  make restart         - Startet den Dienst neu"
	@echo "  make status          - Zeigt Status des Dienstes"
	@echo "  make logs            - Zeigt Live-Logs vom Dienst"
	@echo "  make backup-config   - Sichert die Konfiguration"
	@echo "  make uninstall       - Entfernt alles außer Konfiguration"
	@echo ""

install:
	sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
	sudo git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git $(BASE_DIR) || true
	sudo chown -R $(USER):$(USER) $(BASE_DIR)
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install --upgrade pip
	$(VENV)/bin/pip install -r $(BASE_DIR)/requirements.txt

	sudo tee /etc/systemd/system/$(SERVICE) > /dev/null <<EOF
[Unit]
Description=Modbus TCP Proxy Service
After=network.target

[Service]
ExecStart=$(PYTHON) $(BASE_DIR)/modbus_tcp_proxy.py --config $(CONFIG)
WorkingDirectory=$(BASE_DIR)
Restart=always
User=$(USER)
Environment="PYTHONUNBUFFERED=1"

[Install]
WantedBy=multi-user.target
EOF

	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE)
	@echo "Installation abgeschlossen. Dienst läuft."

update:
	@echo "Aktualisiere Repository und Abhängigkeiten..."
	git -C $(BASE_DIR) pull
	source $(VENV)/bin/activate && pip install --upgrade -r $(BASE_DIR)/requirements.txt
	sudo systemctl restart $(SERVICE)
	@echo "Update abgeschlossen und Dienst neu gestartet!"

start:
	sudo systemctl start $(SERVICE)

stop:
	sudo systemctl stop $(SERVICE)

restart:
	sudo systemctl restart $(SERVICE)

status:
	sudo systemctl status $(SERVICE)

logs:
	sudo journalctl -u $(SERVICE) -f

backup-config:
	@echo "Sichere Konfiguration nach ~/$(APP_NAME)_config_backup.yaml"
	cp $(CONFIG) ~/$(APP_NAME)_config_backup.yaml
	@echo "Backup abgeschlossen."

uninstall:
	@echo "Stoppe und entferne Dienst..."
	sudo systemctl stop $(SERVICE) || true
	sudo systemctl disable $(SERVICE) || true
	sudo rm -f /etc/systemd/system/$(SERVICE)
	sudo systemctl daemon-reload

	@echo "Lösche Installationsverzeichnis: $(BASE_DIR)"
	sudo rm -rf $(BASE_DIR)

	@echo "Optional: Konfigurationsverzeichnis erhalten:"
	@echo "  $(CONFIG_DIR)"
	@echo "Wenn du willst, kannst du das manuell löschen."

	@echo "Uninstallation abgeschlossen!"
