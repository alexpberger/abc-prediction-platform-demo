# Project Instructions — ABC Prediction Platform

## 1. Project purpose

This repository contains `abc-prediction-platform`, a production-oriented prediction-market platform built around Kalshi.

The platform demonstrates how an autonomous agent can operate on shared trading infrastructure. The agent researches prediction markets and proposes trades.

The platform emphasizes modular architecture, reliable data processing, deterministic risk management, automated testing, security, CI/CD, and cloud deployment.

The objective is to demonstrate how AI-driven decision-making can be integrated into a maintainable, observable, and production-oriented software platform.

## 2. Long-term product vision

An autonomous agent explores prediction markets, researches opportunities, formulates hypotheses, and proposes trades.

### Shared platform

The platform uses shared capabilities for:

- Market data.
- Trading proposals and execution.
- Deterministic risk management.
- Portfolio and P&L.
- Persistence and auditability.
- Monitoring and observability.

All trading must use paper trading by default. Live trading is out of scope unless explicitly approved by the user.

## 3. Architectural principles

- Backend: Python and FastAPI.
- Frontend: React and TypeScript.
- Database: PostgreSQL.
- Event streaming: Apache Kafka.
- Containerization: Docker.
- Development environment: Cursor with VS Code Dev Containers.
- Cloud target: Microsoft Azure.
- Infrastructure as Code: Terraform.
- CI/CD: GitHub Actions.

Start with a modular monolith: one primary FastAPI application with clear internal module boundaries.

Keep market data, trading, risk, execution, portfolio, and strategy responsibilities separate.

Use PostgreSQL as the authoritative store for persistent business data. Introduce Kafka incrementally when there is a concrete use case and learning benefit.

Prefer simple, testable solutions over unnecessary abstraction, microservices, or infrastructure.

These are target architectural principles, not permission to implement the entire stack at once. Follow the current implementation stage and the user's explicit task.

## 4. Working agreement

The user controls the scope, priorities, and pace of development.

- Treat the user's latest prompt as the definition of the current task.
- Implement only what is requested and what is strictly necessary to complete it.
- Do not independently expand the task into future roadmap items.
- Do not introduce new frameworks, services, dependencies, or architectural patterns without a clear need.
- Do not rewrite unrelated files or refactor unrelated code.
- Do not implement future features merely because they are described in this document.
- If an important decision is unspecified and materially affects the solution, ask before proceeding.
- For larger or ambiguous tasks, first summarize the proposed approach and wait for approval.
- For small, clearly specified tasks, proceed directly within the requested scope.
- Do not perform destructive operations or change external infrastructure without explicit approval.
- Never introduce real credentials, secrets, or personal data into source control.

When the user requests a plan or review rather than implementation, provide the plan or review without modifying the codebase.

## 5. Quality and security

- Prefer readable, maintainable, explicitly structured code.
- Validate external inputs and handle errors deliberately.
- Keep business logic separate from API routing and infrastructure concerns.
- Add or update relevant tests when changing behavior.
- Never claim that tests pass unless they have actually been executed successfully.
- Use reproducible dependency installations and respect existing lockfiles.
- Follow least-privilege principles and avoid exposing secrets.
- Keep configuration environment-specific.
- Preserve the separation between strategy decisions and deterministic risk/execution controls.
- Record important architectural decisions as the project evolves.

## 6. Completion criteria

For implementation tasks:

1. Make only the agreed changes.
2. Run relevant tests or checks when feasible.
3. Report the files changed and the purpose of each change.
4. Report tests and checks performed, including failures or limitations.
5. Identify any remaining manual steps.
6. Mention follow-up ideas separately; do not implement them without approval.

Do not claim that a feature is production-ready merely because it works locally.

## 7. Current development priority

The initial priority is to establish a clean, reproducible development environment and a minimal working application.

The first milestone is:

- Repository and project structure.
- React + TypeScript frontend.
- FastAPI backend.
- Initial login-page UI.
- Basic frontend/backend integration.
- Reproducible local startup.
- Initial documentation.

Database integration, real authentication, Azure deployment, Terraform, Kafka, and trading functionality will be introduced incrementally as explicitly requested.

**Guiding principle: Build the requested next step, keep the long-term architecture in mind, and let the user decide when to expand the scope.**