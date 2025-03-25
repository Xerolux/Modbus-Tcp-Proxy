APP_NAME = Modbus-Tcp-Proxy
BASE_DIR = /opt/$(APP_NAME)
CONFIG   = /etc/$(APP_NAME)/config.yaml
VENV     = $(BASE_DIR)/venv
PYTHON   = $(VENV)/bin/python3
SERVICE  = modbus_proxy.service

.PHONY: help install update start stop restart status logs

help:
	@echo ""
	@echo "Verfügbare Befehle:"
	@echo "  make install     - Installiert alles und richtet den Dienst ein"
	@echo "  make update      - Holt neueste Version aus Git & installiert neu"
	@echo "  make start       - Startet den systemd-Dienst"
	@echo "  make stop        - Stoppt den systemd-Dienst"
	@echo "  make restart     - Startet den Dienst neu"
	@echo "  make status      - Zeigt den Status des Dienstes"
	@echo "  make logs        - Zeigt die Log-Ausgabe live"
	@echo ""

install:
	sudo apt update && sudo apt install -y python3 python3-pip python3-venv git
	sudo git clone https://github.com/Xerolux/Modbus-Tcp-Proxy.git $(BASE_DIR) || true
	sudo chown -R $(USER):$(USER) $(BASE_DIR)
	python3 -m venv $(VENV)
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
Environment=\"PYTHONUNBUFFERED=1\"

[Install]
WantedBy=multi-user.target
EOF

	sudo systemctl daemon-reload
	sudo systemctl enable --now $(SERVICE)

update:
	git -C $(BASE_DIR) pull
	$(VENV)/bin/pip install -r $(BASE_DIR)/requirements.txt
	sudo systemctl restart $(SERVICE)

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
