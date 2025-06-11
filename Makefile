UV := $(HOME)/.local/bin/uv
PYTHON_VERSION := 3.11
UV_INSTALL_SCRIPT := https://astral.sh/uv/install.sh
PATH := $(HOME)/.local/bin:$(PATH)

.PHONY: check-uv
check-uv:		## Check and install uv if necessary
	@if command -v $(UV) >/dev/null 2>&1; then \
		echo "📦 uv is already installed."; \
	else \
		echo "📦 uv is not installed. Installing uv..."; \
		curl -LsSf $(UV_INSTALL_SCRIPT) | sh; \
	fi; \
	if ! command -v $(UV) >/dev/null 2>&1; then \
		echo "❌  uv is not in your PATH. Please add the uv installation directory to your PATH environment variable."; \
		exit 1; \
	fi

.PHONY: install-python
install-python: check-uv	## Install Python with uv
	@echo "🐍 Installing Python $(PYTHON_VERSION) with uv"
	@$(UV) python install $(PYTHON_VERSION)
	@echo "🐍 Configuring Python $(PYTHON_VERSION) as the default Python version"
	@$(UV) python pin $(PYTHON_VERSION)
	@echo "🐍 Python installation complete."

.PHONY: install
install: install-python		## Install core dependencies
	# @echo "📦 Installing core dependencies with uv"
	@$(UV) sync --group controller --group core
	@echo "🔧 Installing pre-commit hooks"
	@$(UV) run pre-commit install
	@echo ""
	@$(MAKE) update-dockers
	@echo ""
	@$(MAKE) shell

.PHONY: install-production
install-production: install	## Install production dependencies
	@echo "🐳 Updating production docker images..."
	@echo "🐳 Building nebula-waf"
	@docker build -t nebula-waf -f nebula/addons/waf/Dockerfile-waf --build-arg USER=$(USER) nebula/addons/waf
	@echo "🐳 Building nebula-loki"
	@docker build -t nebula-waf-loki -f nebula/addons/waf/Dockerfile-loki nebula/addons/waf
	@echo "🐳 Building nebula-promtail"
	@docker build -t nebula-waf-promtail -f nebula/addons/waf/Dockerfile-promtail --build-arg USER=$(USER) nebula/addons/waf
	@echo "🐳 Building nebula-grafana"
	@docker build -t nebula-waf-grafana -f nebula/addons/waf/Dockerfile-grafana --build-arg USER=$(USER) nebula/addons/waf
	echo "🐳 Docker images updated."

.PHONY: shell
shell:				## Start a shell in the uv environment
	@echo "🐚 Starting a shell in the uv environment"
	@if [ -n "$$VIRTUAL_ENV" ]; then \
		echo "🐚 Already in a virtual environment: $$VIRTUAL_ENV"; \
	elif [ ! -d ".venv" ]; then \
		echo "❌ .venv directory not found. Running 'make install' to create it..."; \
		$(MAKE) install; \
	else \
		echo "🐚 Run the following command to activate the virtual environment:"; \
		echo ""; \
		echo '[Linux/MacOS]	\033[1;32msource .venv/bin/activate\033[0m'; \
		echo '[Windows]	\033[1;32m.venv\\bin\\activate\033[0m'; \
		echo ""; \
		echo "🚀 NEBULA is ready to use!"; \
	fi

.PHONY: update-dockers
update-dockers:				## Update docker images
	@echo "🐳 Updating docker images..."
	@echo "🐳 Building nebula-controller docker image. Do you want to continue (overrides existing image)? (y/n)"
	@read ans; if [ "$${ans:-N}" = y ]; then \
		docker build -t nebula-controller -f nebula/controller/Dockerfile .; \
	else \
		echo "Skipping nebula-controller docker build."; \
	fi
	@echo ""
	@echo "🐳 Building nebula-frontend docker image. Do you want to continue (overrides existing image)? (y/n)"
	@read ans; if [ "$${ans:-N}" = y ]; then \
		docker build -t nebula-frontend -f nebula/frontend/Dockerfile .; \
	else \
		echo "Skipping nebula-frontend docker build."; \
	fi
	@echo ""
	@echo "🐳 Building nebula-core docker image. Do you want to continue (overrides existing image)? (y/n)"
	@read ans; if [ "$${ans:-N}" = y ]; then \
		docker build -t nebula-core .; \
	else \
		echo "Skipping nebula-core docker build."; \
	fi
	echo "🐳 Docker images updated."

.PHONY: update
update:				## Update NEBULA code
	@echo "🔄 Updating NEBULA code..."
	@echo "🔄 Pulling latest changes from the repository..."
	@git pull origin main
	@echo "🔄 Updating submodules..."
	@git submodule update --init --recursive
	@echo "🔄 NEBULA code updated."

.PHONY: lock
lock:				## Update the lock file
	@echo "🔒 This will update the lock file. Do you want to continue? (y/n)"
	@read ans && [ $${ans:-N} = y ] || { echo "Lock cancelled."; exit 1; }
	@echo "🔒 Locking dependencies..."
	@$(UV) lock

.PHONY: check
check:				## Run code quality tools
	@echo "🛠️ Running code quality checks"
	@$(UV) run pre-commit run -a

.PHONY: check-plus
check-plus: check		## Run additional code quality tools
	@echo "🔍 Checking code formatting with black"
	@$(UV) run black --check .
	@echo "⚙️ Static type checking with mypy"
	@$(UV) run mypy
	@echo "🔎 Checking for obsolete dependencies"
	@$(UV) run deptry .

.PHONY: build
build: clean-build		## Build the wheel file
	@echo "🚀 Creating wheel file"
	@$(UV) build

.PHONY: clean-build
clean-build:			## Clean build artifacts
	@rm -rf dist

.PHONY: publish
publish:			## Publish a release to PyPI
	@echo "🚀 Publishing..."
	@$(UV) publish --token $(PYPI_TOKEN)

.PHONY: build-and-publish
build-and-publish: build publish	## Build and publish the package

.PHONY: doc-install
full-install: install-python	## Install dependencies for documentation
	@echo "📦 Installing doc dependencies with uv"
	@$(UV) sync --group core --group docs
	@$(MAKE) shell

.PHONY: doc-test
doc-test:			## Test if documentation can be built without errors
	@$(UV) run mkdocs build -f docs/mkdocs.yml -d _build -s

.PHONY: doc-build
doc-build:			## Build the documentation
	@$(UV) run mkdocs build -f docs/mkdocs.yml -d _build

.PHONY: doc-serve
doc-serve:			## Serve the documentation locally
	@$(UV) run mkdocs serve -f docs/mkdocs.yml

.PHONY: clean
clean: clean-build		## Clean up build artifacts and caches
	@echo "🧹 Cleaning up build artifacts and caches"
	@rm -rf __pycache__ */__pycache__ .mypy_cache

.PHONY: help
help:				## Display available commands
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "💡 \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
