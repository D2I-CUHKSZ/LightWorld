# Backend Architecture (Refactored)

This repository is now backend-only.

## Layering

- `backend/app/cli/`
  - Standardized CLI entrypoints (API, local pipeline, parallel simulation)
- `backend/app/core/`
  - Core settings/runtime shared primitives
- `backend/app/adapters/http/`
  - HTTP adapters (Blueprints, request/response handling)
- `backend/app/application/`
  - Legacy service layer used by APIs and scripts
- `backend/app/domain/`
  - Domain entities/state managers (project/task)
- `backend/app/infrastructure/`
  - Infrastructure utilities (LLM client, logger, parser, paging)
- `backend/app/modules/`
  - Refactored application modules (domain-oriented)

## New Module Structure

- `backend/app/modules/graph/local_pipeline.py`
  - `LocalGraphPipeline`: local-document pipeline orchestration
  - `LocalPipelineOptions`: pipeline input contract
- `backend/app/modules/simulation/runtimes.py`
  - `TopologyAwareRuntime`: topology-aware coordination + differentiation
  - `SimpleMemRuntime`: incremental memory build/retrieval
- `backend/app/modules/simulation/platform_runner.py`
  - `PlatformSpec`: platform strategy descriptor
  - `run_platform_simulation`: shared loop for Twitter/Reddit
  - `TWITTER_SPEC` / `REDDIT_SPEC`: platform-specific strategy instances

## Design Patterns Applied

- Strategy:
  - Platform behavior differences are represented by `PlatformSpec`.
- Application Service:
  - Complex use cases are encapsulated in `LocalGraphPipeline` and `run_platform_simulation`.
- Thin Entry Script:
  - `scripts/run_local_pipeline.py` and `scripts/run_parallel_simulation.py` now focus on CLI and orchestration.

## Operational Entry Points

- API server:
  - `cd backend && uv run mirofish-api`
- Local graph build (no frontend):
  - `cd backend && uv run mirofish-local-pipeline ...`
- Parallel simulation:
  - `cd backend && uv run mirofish-parallel-sim --config <path>`

## Compatibility Wrappers

- `backend/run.py` and `backend/scripts/run_local_pipeline.py` are kept as legacy wrappers.
- Existing old commands still work, but new CLI commands are preferred.
