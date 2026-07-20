# Makefile for PraxisFlow
# Developer commands for local development, testing, and deployment

.PHONY: help dev test lint build push deploy clean

# ─── Default ───
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Development ───
dev: ## Start all services in development mode
	docker compose up -d

dev-down: ## Stop development services
	docker compose down -v

dev-logs: ## Follow development logs
	docker compose logs -f

dev-shell: ## Open shell in backend container
	docker compose exec backend bash

dev-frontend-shell: ## Open shell in frontend container
	docker compose exec frontend sh

# ─── Database ───
db-migrate: ## Run database migrations
	docker compose exec backend prisma migrate deploy

db-migrate-dev: ## Create and apply new migration
	docker compose exec backend prisma migrate dev

db-studio: ## Open Prisma Studio
	docker compose exec backend prisma studio

db-reset: ## Reset database (WARNING: destroys data)
	docker compose exec backend prisma migrate reset --force

db-seed: ## Seed database with test data
	docker compose exec backend python -m scripts.seed

# ─── Backend Commands ───
backend-install: ## Install backend dependencies
	cd backend && pip install -r requirements.txt

backend-test: ## Run backend unit tests
	cd backend && pytest tests/ -v --cov=app --cov-report=term-missing

backend-test-integration: ## Run backend integration tests
	cd backend && pytest tests/integration/ -v

backend-test-watch: ## Run tests in watch mode
	cd backend && pytest-watch tests/

backend-lint: ## Lint backend code
	cd backend && ruff check app/ tests/
	cd backend && ruff format --check app/ tests/

backend-lint-fix: ## Fix linting issues
	cd backend && ruff check --fix app/ tests/
	cd backend && ruff format app/ tests/

backend-typecheck: ## Run mypy type checking
	cd backend && mypy app/ --strict --ignore-missing-imports

backend-shell: ## Open Python shell in backend context
	cd backend && python -m IPython

# ─── Frontend Commands ───
frontend-install: ## Install frontend dependencies
	cd frontend && npm ci

frontend-dev: ## Start frontend dev server
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build

frontend-test: ## Run frontend tests
	cd frontend && npm test

frontend-test-watch: ## Run frontend tests in watch mode
	cd frontend && npm run test:watch

frontend-lint: ## Lint frontend code
	cd frontend && npm run lint

frontend-lint-fix: ## Fix frontend linting
	cd frontend && npm run lint -- --fix

frontend-typecheck: ## Run TypeScript type checking
	cd frontend && npx tsc --noEmit

# ─── LLM Gateway ───
gateway-build: ## Build LLM Gateway image
	docker build -t praxisflow/llm-gateway:latest ./llm-gateway

gateway-run: ## Run LLM Gateway locally
	docker compose -f llm-gateway/docker-compose.yml up -d

gateway-test: ## Test LLM Gateway
	curl -X POST http://localhost:4000/v1/chat/completions \
	  -H "Content-Type: application/json" \
	  -H "Authorization: Bearer sk-proxy-master-key" \
	  -d '{"model": "groq/llama-3.3-70b-versatile", "messages": [{"role": "user", "content": "Hello"}]}'

# ─── Guardrails ───
guardrails-test: ## Test guardrails
	cd backend && python -m pytest tests/guardrails/ -v

# ─── Observability ───
otel-run: ## Start OpenTelemetry collector
	docker compose -f infrastructure/otel/docker-compose.yml up -d

langfuse-run: ## Start Langfuse
	docker compose -f infrastructure/langfuse/docker-compose.yml up -d

# ─── Full Test Suite ───
test: backend-test frontend-test guardrails-test ## Run all tests

test-full: backend-test backend-test-integration frontend-test guardrails-test ## Run all tests including integration

# ─── Code Quality ───
lint: backend-lint frontend-lint ## Run all linters

lint-fix: backend-lint-fix frontend-lint-fix ## Fix all linting issues

typecheck: backend-typecheck frontend-typecheck ## Run all type checks

# ─── Build ───
build: ## Build all Docker images
	docker compose build
	docker build -t praxisflow/llm-gateway:latest ./llm-gateway

build-prod: ## Build production images
	docker compose -f docker-compose.prod.yml build

# ─── Security ───
security-scan: ## Run security scans
	trivy fs --severity HIGH,CRITICAL .
	trivy image praxisflow/backend:latest
	trivy image praxisflow/frontend:latest
	trivy image praxisflow/llm-gateway:latest

secrets-scan: ## Scan for secrets
	trufflehog filesystem .

# ─── Load Testing ───
load-test-api: ## Run API load test
	k6 run tests/load/api-load-test.js

load-test-ws: ## Run WebSocket load test
	k6 run tests/load/websocket-load-test.js

load-test-full: ## Run full load test suite
	k6 run tests/load/api-load-test.js && k6 run tests/load/websocket-load-test.js

# ─── Deployment ───
deploy-staging: ## Deploy to staging
	./scripts/deploy.sh staging

deploy-prod: ## Deploy to production (requires approval)
	./scripts/deploy.sh production

# ─── Cleanup ───
clean: ## Clean up Docker resources
	docker compose down -v --remove-orphans
	docker system prune -f

clean-all: ## Deep clean (WARNING: removes all Docker data)
	docker compose down -v --remove-orphans
	docker system prune -af --volumes

# ─── Utilities ───
logs-backend: ## Follow backend logs
	docker compose logs -f backend

logs-frontend: ## Follow frontend logs
	docker compose logs -f frontend

logs-worker: ## Follow worker logs
	docker compose logs -f worker

logs-gateway: ## Follow LLM Gateway logs
	docker compose -f llm-gateway/docker-compose.yml logs -f

# ─── Health Checks ───
health: ## Check all service health
	curl -f http://localhost:8000/health
	curl -f http://localhost:3000/api/health
	curl -f http://localhost:6333/healthz
	curl -f http://localhost:7474/

# ─── Generate ───
generate-prisma: ## Generate Prisma client
	cd backend && prisma generate

generate-openapi: ## Generate OpenAPI spec
	cd backend && python -m scripts.generate_openapi

# ─── Documentation ───
docs-serve: ## Serve documentation locally
	cd docs && mkdocs serve

docs-build: ## Build documentation
	cd docs && mkdocs build