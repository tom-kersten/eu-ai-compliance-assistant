# Offline profile

Self-hosted LLM and embedding servers via the Compose `offline` profile
(`vllm-llm` and `vllm-embed`). The default online stack is unchanged. The
backend does not depend on the vLLM services; point base URLs at them through
`.env.offline`.

## Usage

1. Copy and edit the offline env for your hardware and models:

   ```bash
   cp .env.offline.example .env.offline
   # edit .env.offline (quantization, max context, extra args)
   ```

2. Start the stack (db, migrate, backend, frontend, both vLLM services):

   ```bash
   make up-offline
   ```

3. Ingest with the offline embedding endpoint (T9; real ingestion, not a stub).
   Use `ingest-reset` to clear and rebuild from scratch:

   ```bash
   make ingest ENV_FILE=.env.offline
   # or: make ingest-reset ENV_FILE=.env.offline
   ```

4. Opt-in live checks against the local endpoints:

   ```bash
   make test-live ENV_FILE=.env.offline
   ```

An index is built and queried with the same serving setup. Switching profile
means running ingestion again.

## Hardware

- Both services reserve every NVIDIA GPU (`deploy.resources.reservations.devices`).
- `Qwen/Qwen3.8-27B` in BF16 is on the order of 56 GB of weights plus KV cache
  for `LLM_MAX_MODEL_LEN`. Plan VRAM accordingly, or use quantization (below).
- `Qwen/Qwen3-Embedding-8B` needs several gigabytes more; sharing one GPU between
  both services is possible only with reduced context length and/or quantization.
- Model weights are cached in the named Compose volume `hf-cache`
  (`HF_HOME=/root/.cache/huggingface`).

## Quantization

Quantization is the deployer's choice (see `docs/REFERENCE.md`). Pass flags
through the compose-only variables (not in `app/config.py`):

| Variable | Role |
|---|---|
| `VLLM_LLM_EXTRA_ARGS` | Extra CLI args for `vllm-llm` (e.g. `--quantization fp8`) |
| `VLLM_EMBED_EXTRA_ARGS` | Extra CLI args for `vllm-embed` (default includes `--runner pooling`) |

Alternatives:

- Point `LLM_LOCAL_MODEL` at a pre-quantized repo such as `Qwen/Qwen3.8-27B-FP8`
  instead of adding `--quantization`.
- Lower `LLM_MAX_MODEL_LEN` to shrink the KV cache.

Quantization changes embedding vectors slightly. Re-ingest after changing the
embedding serving setup (`make ingest-reset ENV_FILE=.env.offline`).

Optional Matryoshka override for `dimensions=2000` (quoting is shell-sensitive;
prefer editing the compose command only if a live run shows `dimensions`
rejected):

```text
--hf-overrides '{"is_matryoshka": true}'
```

## Maximum context length

`LLM_MAX_MODEL_LEN` is passed to vLLM as `--max-model-len`. The example value
`8192` is hardware-conservative; the model's nominal window on OpenRouter is
much larger.

`PROMPT_TOKEN_BUDGET` counts **retrieved provision tokens only**
(`app/pipeline/budget.py`). Derive it from the max model length so the prompt
template, the question, and the completion still fit:

```text
PROMPT_TOKEN_BUDGET ≈ LLM_MAX_MODEL_LEN / 2
```

The example pairs `LLM_MAX_MODEL_LEN=8192` with `PROMPT_TOKEN_BUDGET=4096`.

## Served model name

vLLM `--model` is the Hugging Face weights id (`LLM_LOCAL_MODEL` /
`EMBEDDING_LOCAL_MODEL`). `--served-model-name` must equal the names the
backend sends in API requests:

| Service | `--model` | `--served-model-name` |
|---|---|---|
| `vllm-llm` | `LLM_LOCAL_MODEL` | `SELECTION_MODEL` (and `ANSWER_MODEL`, same default) |
| `vllm-embed` | `EMBEDDING_LOCAL_MODEL` | `EMBEDDING_MODEL` |

Misalignment makes `/v1/models` and chat/embeddings calls fail with an unknown
model id.

## Image

Pinned Compose image: `vllm/vllm-openai:v0.31.0` (vLLM 0.31.0, default CUDA
13.0 tag). Do not use `latest`. A CUDA 12.9 variant (`v0.31.0-cu129`) exists
upstream; this repository pins the default tag only.

## Flags

Compose-only variables and CLI flags for the offline profile. Marked
**Verified** only after a recorded live run on this machine; otherwise
**Unverified**.

| Flag / setting | Status | Notes |
|---|---|---|
| Image `vllm/vllm-openai:v0.31.0` | Unverified | Pin only; not live-tested here |
| `--served-model-name` = `SELECTION_MODEL` / `EMBEDDING_MODEL` | Unverified | |
| `--max-model-len` via `LLM_MAX_MODEL_LEN` | Unverified | Example `8192` |
| `VLLM_LLM_EXTRA_ARGS` (quantization empty by default) | Unverified | |
| `VLLM_EMBED_EXTRA_ARGS=--runner pooling` | Unverified | Required for embedding models |
| Optional `--hf-overrides` Matryoshka JSON | Unverified | Quoting-sensitive; not in the example default |
| Embedding `dimensions=2000` on vLLM | Unverified | Caught by live endpoint / reliability tests |
| Healthcheck `/health` (Python urllib) | Unverified | `start_period` 600s |
| Reasoning request format | Unverified | The adapter sends OpenRouter's `reasoning` field (`openrouter_reasoning_params()`); a vLLM-specific mapping is not written yet |

### Live verification record

Attempted 2026-10-09 on NVIDIA GeForce RTX 4070 Ti (12 GiB, WSL2).
`make up-offline` started both containers; each exited during EngineCore
init with:

```text
ValueError: Free memory on device cuda:0 (10.78/11.99 GiB) on startup is less
than desired GPU memory utilization (0.92, 11.03 GiB).
```

Root cause: example BF16 weights (`Qwen/Qwen3.8-27B` ~56 GB, plus
`Qwen/Qwen3-Embedding-8B`) do not fit this card, and both services reserve
every GPU so they cannot share it. `make ingest ENV_FILE=.env.offline` and
`make test-live ENV_FILE=.env.offline` were therefore not run. All flags above
remain **Unverified**. Re-try on hardware that fits the chosen quantization
and context length, then record row count, wall time, and flip flags to
Verified.
