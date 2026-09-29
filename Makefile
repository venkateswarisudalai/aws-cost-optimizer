# aws-cost-optimizer
#
# Everything runs locally. No AWS credentials are ever built into an image or
# sent anywhere but the AWS APIs themselves.

SHELL := /bin/bash
IMAGE := aws-cost-optimizer:local
PROFILE ?= default
PORT ?= 3000

.DEFAULT_GOAL := help
.PHONY: help build demo scan dashboard test lint shell clean

help: ## Show available targets
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "  Examples:"
	@echo "    make demo                      # explore with fake data, no AWS account"
	@echo "    make dashboard PROFILE=vis     # scan a real account, read-only"
	@echo "    make scan PROFILE=vis          # one-shot CLI scan"

build: ## Build the Docker image (dashboard + API)
	docker build -t $(IMAGE) .

demo: build ## Dashboard with demo data — no credentials touched
	@echo "→ http://localhost:$(PORT)  (demo data)"
	docker run --rm -p 127.0.0.1:$(PORT):3000 $(IMAGE) \
		serve --host 0.0.0.0 --port 3000 --demo-data

dashboard: build ## Dashboard against a real account (PROFILE=...)
	@echo "→ http://localhost:$(PORT)  (profile: $(PROFILE), read-only)"
	docker run --rm -p 127.0.0.1:$(PORT):3000 \
		-v "$$HOME/.aws:/home/awsco/.aws:ro" \
		-v awsco-data:/data \
		-e AWS_PROFILE=$(PROFILE) \
		$(IMAGE) serve --host 0.0.0.0 --port 3000

scan: build ## One-shot CLI scan of every enabled region (PROFILE=...)
	docker run --rm \
		-v "$$HOME/.aws:/home/awsco/.aws:ro" \
		-v awsco-data:/data \
		-e AWS_PROFILE=$(PROFILE) \
		$(IMAGE) scan

test: ## Run the backend test suite
	cd backend && .venv-dev/bin/python -m pytest -q

lint: ## Ruff + tsc
	cd backend && .venv-dev/bin/python -m ruff check awsco
	cd frontend && npm run typecheck

shell: build ## Shell into the image for debugging
	docker run --rm -it --entrypoint /bin/bash $(IMAGE)

clean: ## Remove the image and the scan-history volume
	-docker rmi $(IMAGE)
	-docker volume rm awsco-data
