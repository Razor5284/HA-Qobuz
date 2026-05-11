# HA-Qobuz development helpers
#
# Usage:
#   make test            — run the pytest suite
#   make lint            — run ruff check
#   make test-api        — test Qobuz API login (requires email+password env vars)
#   make deploy-local    — copy custom_components/qobuz to a local HA instance
#   make deploy-ssh      — deploy to a remote HA via SSH

.PHONY: test lint test-api deploy-local deploy-ssh

# Path to your local Home Assistant config directory
HA_CONFIG_DIR ?= $(HOME)/.homeassistant
# SSH target for remote HA (e.g. user@homeassistant.local or user@192.168.x.x)
HA_SSH_TARGET ?= root@homeassistant.local
HA_SSH_CONFIG_DIR ?= /config

test:
	pytest tests/ -v --tb=short

lint:
	ruff check .

test-api:
	@if [ -z "$$QOBUZ_TOKEN" ]; then \
		echo "Usage: QOBUZ_TOKEN=your_token_here make test-api"; \
		echo "Get your token from play.qobuz.com → F12 → Application → Local Storage → localuser → token"; \
		exit 1; \
	fi
	python3 scripts/test_api.py "$$QOBUZ_TOKEN"

# Copies integration files to a local HA config directory, then reminds you to restart.
# Useful when HA runs on the same machine (e.g. in Docker with a volume mount, or HA OS VM).
deploy-local:
	@echo "Deploying to $(HA_CONFIG_DIR)/custom_components/qobuz ..."
	mkdir -p "$(HA_CONFIG_DIR)/custom_components/qobuz"
	cp -r custom_components/qobuz/. "$(HA_CONFIG_DIR)/custom_components/qobuz/"
	@echo "Done. Restart Home Assistant to pick up the changes."

# Deploys to a remote HA instance via SSH (e.g. HA OS, Raspberry Pi).
deploy-ssh:
	@echo "Deploying to $(HA_SSH_TARGET):$(HA_SSH_CONFIG_DIR)/custom_components/qobuz ..."
	ssh $(HA_SSH_TARGET) "mkdir -p $(HA_SSH_CONFIG_DIR)/custom_components/qobuz"
	scp -r custom_components/qobuz/. $(HA_SSH_TARGET):$(HA_SSH_CONFIG_DIR)/custom_components/qobuz/
	@echo "Done. Restart Home Assistant (or run: ssh $(HA_SSH_TARGET) 'ha core restart')"
