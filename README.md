# Beanly

Stage 0-2: FastAPI, PostgreSQL, Redis, Celery, Next.js, authentication,
organizations, locations, and tenant context.

```bash
docker compose up --build
```

Optional local photo/PDF menu extraction uses Ollama and does not require an OpenAI key:

```bash
# Set AI_EXTRACTION_PROVIDER=ollama in .env, then:
docker compose --profile ai up --build
```

The `ai` profile pulls `qwen3-vl:4b` once. Without the profile/provider flag, AI import stays disabled.

- Frontend: http://localhost:3000
- API docs: http://localhost:8000/docs
- Liveness: http://localhost:8000/health/live
- Readiness: http://localhost:8000/health/ready

Copy `.env.example` to `.env` and replace `JWT_SECRET` before any non-local deployment.

Run the complete backend gate, including PostgreSQL and Alembic schema checks:

```bash
docker compose -f compose.yaml -f compose.test.yaml run --build --rm backend-test
```

The first authenticated session opens onboarding. Creating a workspace writes
the organization, its primary location, and the creator's `OWNER` membership in
one transaction, then opens `/app`. Organization and location selection is kept
as validated UUID hints in browser storage; access tokens remain in memory.
