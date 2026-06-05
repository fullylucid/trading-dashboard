# FinTube Vision — the "eyes" tier

FinTube turns pixels → text (read a video title off a screenshot, describe a thumbnail,
caption/score a keyframe) and lets the text Opus pool reason over that text. There are **two
interchangeable backends**:

1. **Claude worker pool (default).** The Opus worker pool *is* Claude Code, which can `Read`
   image files natively. The backend stages the image in a shared dir and enqueues a normal
   text job — *"Read the image at `<path>` and …"*. **Free under the Max subscription**, no
   extra service. Requires a dir shared between the backend container and the host where the
   workers run.
2. **External VLM endpoint (optional override).** Any OpenAI-compatible vision
   `/v1/chat/completions` (SmolVLM via llama.cpp, moondream via Ollama, …). Set
   `FINTUBE_VLM_URL` and it takes precedence over the pool — cheaper/faster per call.

If neither is configured the vision layer is a no-op — `/api/fintube/find` returns
`status: "vision-unconfigured"` and nothing else changes. **No torch in the backend image**
either way.

---

## Default: Claude worker pool (no extra service)

The backend writes images to a dir that's bind-mounted into the container **and** visible to
the host Claude workers at the same files. `docker-compose.box.yml` already wires this:

```yaml
# backend service:
environment:
  FINTUBE_VISION_DIR: /vision                                        # container path the backend writes to
  FINTUBE_VISION_DIR_HOST: /home/user/.config/trading-dashboard/vision  # same dir as the worker sees it
volumes:
  - /home/user/.config/trading-dashboard/vision:/vision             # shared rw with the host workers
```

Just redeploy the backend (`docker compose -f docker-compose.box.yml up -d --build backend`)
and vision is on — `vision-status` reports `{"configured": true, "backend": "pool"}`. To turn
it off, set `FINTUBE_VISION_POOL=0`.

---

## Optional override: external VLM endpoint

Prefer a tiny local model (faster, cheaper than a full Claude turn)? Stand one up and set
`FINTUBE_VLM_URL`; it overrides the pool.

## Option A — llama.cpp `llama-server` (CPU-friendly, lean — recommended)

SmolVLM is tiny (256M/500M/2.2B); the 500M GGUF runs fine on CPU.

```bash
# build/install llama.cpp (or use a prebuilt llama-server binary)
# grab a SmolVLM GGUF + its vision projector (mmproj) from HuggingFace, e.g.:
#   ggml-org/SmolVLM-500M-Instruct-GGUF  (model + mmproj-*.gguf)

llama-server \
  -m   SmolVLM-500M-Instruct-Q8_0.gguf \
  --mmproj mmproj-SmolVLM-500M-Instruct-f16.gguf \
  --host 0.0.0.0 --port 8080 \
  --ctx-size 4096
# -> OpenAI-compatible API at http://<host>:8080/v1
```

## Option B — vLLM (GPU)

```bash
pip install vllm
vllm serve HuggingFaceTB/SmolVLM-Instruct --port 8080
# -> http://<host>:8080/v1
```

## Wire the backend

Point the backend at the endpoint (note the trailing `/v1`) and restart it:

```bash
# in the backend's environment (.env / compose):
FINTUBE_VLM_URL=http://vlm:8080/v1        # required to enable vision
FINTUBE_VLM_MODEL=smolvlm                  # the model name the server reports (optional)
FINTUBE_VLM_TIMEOUT=60                      # seconds (optional)
```

In `docker-compose.box.yml`, the simplest layout is a sidecar `vlm` service on the same
network as `backend`, with `FINTUBE_VLM_URL=http://vlm:8080/v1` set on `backend`.

## Verify

```bash
# is the backend wired up?
curl -s http://127.0.0.1:8000/api/fintube/vision-status
# -> {"configured": true, "model": "smolvlm"}

# resolve a video from an image (base64, no data: prefix)
B64=$(base64 -w0 screenshot.jpg)
curl -s -X POST http://127.0.0.1:8000/api/fintube/find \
  -H 'Content-Type: application/json' \
  -d "{\"image_b64\":\"$B64\",\"mime\":\"image/jpeg\"}" | jq '.status, .read, .candidates[0].title'
```

## Notes
- **Contract:** the backend sends one user message with a `text` part (the task instruction)
  and an `image_url` part carrying an inline `data:<mime>;base64,...` URL — the standard
  OpenAI multimodal shape. Any compliant server works; SmolVLM is just the cheap default.
- **Tiering ("SmolVLM then Claude"):** SmolVLM handles the broad/cheap pass. A future top tier
  can escalate the few highest-value frames to Claude vision for deep analysis.
- Keep the VLM on the LAN / behind the same trust boundary as the backend — it receives raw
  screenshots.
