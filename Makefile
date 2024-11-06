POETRY_HOME := $(HOME)/.poetry
POETRY := $(POETRY_HOME)/bin/poetry

.PHONY: pre-install
pre-install:
	@echo "🐍 Checking if Python is installed"
	@command -v python3 >/dev/null 2>&1 || { echo >&2 "Python is not installed. Aborting."; exit 1; }
	@echo "🐍 Checking Python version"
	@python3 --version | grep -E "Python 3\.(10|[1-9][1-9])" >/dev/null 2>&1 || { echo >&2 "Python version 3.10 or higher is required. Aborting."; exit 1; }
	@echo "📦 Checking if Poetry is installed"
	@command -v poetry >/dev/null 2>&1 || { echo >&2 "Poetry is not installed. Installing Poetry."; curl -sSL https://install.python-poetry.org | POETRY_HOME=$(POETRY_HOME) python3 -; }

.PHONY: install
install: pre-install ## Install the poetry environment and install the pre-commit hooks
	@echo "📦 Installing dependencies with Poetry"
	@PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring $(POETRY) install --with core
	@echo "🔧 Installing pre-commit hooks"
	@$(POETRY) run pre-commit install
	@echo "🐚 Activating virtual environment"
	@$(POETRY) shell

.PHONY: full-install
full-install: pre-install ## Install the poetry environment and install the pre-commit hooks
	@echo "📦 Installing dependencies with Poetry"
	@PYTHON_KEYRING_BACKEND=keyring.backends.null.Keyring $(POETRY) install --with core,docs,dev
	@echo "🔧 Installing pre-commit hooks"
	@$(POETRY) run pre-commit install
	@echo "🐚 Activating virtual environment"
	@$(POETRY) shell

.PHONY: shell
shell: ## Start a shell in the poetry environment
	@echo "🐚 Activating virtual environment"
	@$(POETRY) shell

.PHONY: check
check: ## Run code quality tools.
	@echo "🛠️ Running code quality checks"
	@echo "🔍 Checking Poetry lock file consistency"
	@$(POETRY) check --lock
	@echo "🚨 Linting code with pre-commit"
	@$(POETRY) run pre-commit run -a

.PHONY: check-plus
check-plus: check ## Run additional code quality tools.
	@echo "🔍 Checking code formatting with black
	@$(POETRY) run black --check ."
	@echo "⚙️ Static type checking with mypy"
	@$(POETRY) run mypy
	@echo "🔎 Checking for obsolete dependencies"
	@$(POETRY) run deptry .

.PHONY: build
build: clean-build ## Build wheel file using poetry
	@echo "🚀 Creating wheel file"
	@$(POETRY) build

.PHONY: clean-build
clean-build: ## clean build artifacts
	@rm -rf dist

.PHONY: publish
publish: ## publish a release to pypi.
	@echo "🚀 Publishing: Dry run."
	@$(POETRY) config pypi-token.pypi $(PYPI_TOKEN)
	@$(POETRY) publish --dry-run
	@echo "🚀 Publishing."
	@$(POETRY) publish

.PHONY: build-and-publish
build-and-publish: build publish ## Build and publish.

.PHONY: doc-test
doc-test: ## Test if documentation can be built without warnings or errors
	@$(POETRY) run mkdocs build -f docs/mkdocs.yml -d _build -s

.PHONY: doc-build
doc-build: ## Build the documentation
	@$(POETRY) run mkdocs build -f docs/mkdocs.yml -d _build

.PHONY: doc-serve
doc-serve: ## Build and serve the documentation
	@$(POETRY) run mkdocs serve -f docs/mkdocs.yml

.PHONY: format
format: ## Format code with black and isort
	@echo "🎨 Formatting code"
	@$(POETRY) run black .
	@$(POETRY) run isort .

.PHONY: clean
clean: clean-build ## Clean up build artifacts and cache files
	@echo "🧹 Cleaning up build artifacts and caches"
	@rm -rf __pycache__ */__pycache__ .mypy_cache

.PHONY: help
help:
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "💡 \033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
