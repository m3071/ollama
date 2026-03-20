# Typhoon OCR API

Self-hosted FastAPI OCR service that exposes an OCR.space-style `POST /parse/image` endpoint while using `scb10x/typhoon-ocr1.5-3b` on Ollama behind the scenes.

This build is tuned for fast raw-text OCR:

- raw OCR text only
- no structured extraction
- short prompt
- image downscaling and compression before inference
- `MAX_CONCURRENCY=1`
- `OCR_RETRY_ATTEMPTS=1`
- `MAX_IMAGE_SIDE_PX=1024`
- `OLLAMA_KEEP_ALIVE=24h`
- switchable speed presets via `OCR_SPEED_PRESET=balanced|fastest`

## Run

### One click on Windows

Move this folder to the target machine, connect the machine to the internet for the first run, then double-click one of these files:

```bat
install_and_start.bat
```

or:

```bat
start.bat
```

The first run will automatically:

- install Python 3.12 with `winget` if missing
- install Ollama with `winget` if missing
- install NVIDIA CUDA Toolkit with `winget` if the machine has NVIDIA GPU and CUDA is not found yet
- create `.venv`
- install Python packages from `requirements.txt`
- create `.env` from `.env.example` if missing
- detect whether the machine has a usable GPU
- start Ollama if it is not already running
- pull `scb10x/typhoon-ocr1.5-3b` if it is not installed yet
- start the FastAPI service
- optionally install and start `ngrok` when configured

Later runs reuse the installed runtime and just make sure everything is up.

Requirements for the target Windows machine:

- Windows with PowerShell
- internet access on the first run
- `winget` available (App Installer)

To stop the processes started by this project:

```bat
stop_oneclick.bat
```

### Manual run

```bash
pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000
```

## Environment

Example `.env`:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_MODEL=scb10x/typhoon-ocr1.5-3b
OCR_API_KEY=
MAX_UPLOAD_MB=10
REQUEST_TIMEOUT_SECONDS=45
ALLOWED_MIME_TYPES=image/jpeg,image/png,image/webp,application/pdf
IMAGE_DOWNLOAD_TIMEOUT_SECONDS=15
OCR_SPEED_PRESET=balanced
MAX_IMAGE_SIDE_PX=1024
IMAGE_JPEG_QUALITY=65
SYSTEM_GPU_HINT=unknown
SYSTEM_GPU_NAME=
OLLAMA_ACCELERATION=auto
REQUIRE_GPU=false
INSTALL_CUDA=true
NGROK_ENABLED=false
NGROK_AUTHTOKEN=
NGROK_DOMAIN=
APP_ENV=production
LOG_LEVEL=INFO
MAX_CONCURRENCY=1
OCR_TIMEOUT_SECONDS=45
OCR_RETRY_ATTEMPTS=1
OCR_RETRY_BACKOFF_SECONDS=1
OLLAMA_KEEP_ALIVE=24h
```

Preset behavior:

- `balanced`: uses your configured `MAX_IMAGE_SIDE_PX` and `IMAGE_JPEG_QUALITY`
- `fastest`: overrides them to `768px` and `JPEG quality 55`

Current default: `OCR_SPEED_PRESET=fastest`

## Notes

- `ParsedResults[0].ParsedText` returns raw OCR text only.
- `StructuredData` is always `null`.
- `TextOverlay` is always `null`.
- `detectOrientation` is accepted for compatibility, but `TextOrientation` always returns `"0"`.
- Ollama handles GPU acceleration automatically when the host machine supports it.
- `GET /health/model` now also reports the saved GPU hint from setup via `gpu_hint`, `gpu_name`, and `acceleration`.
- `GET /health/model` also reports runtime GPU state with `gpu_active`, `running_size_vram_bytes`, and `processor_summary`.
- If `REQUIRE_GPU=true`, then `GET /ready` returns `ready: false` until the model is actually running on GPU, and OCR requests return `503`.
- If `INSTALL_CUDA=true`, the startup script installs the CUDA Toolkit on NVIDIA machines when `nvcc` is not found yet.

### Require GPU

If you want this service to refuse CPU fallback, set:

```env
REQUIRE_GPU=true
```

This is useful when the machine should only be considered healthy if Ollama has loaded the configured model onto GPU memory.
- If `NGROK_AUTHTOKEN` is set, the startup script can open an `ngrok` tunnel and print the public HTTPS URL.

### ngrok

Set these values in `.env` if you want a public tunnel:

```env
NGROK_ENABLED=true
NGROK_AUTHTOKEN=your_ngrok_token
NGROK_DOMAIN=
```

If `NGROK_DOMAIN` is empty, ngrok will use a generated domain. If it is set, the startup script will request that domain.

## Endpoints

- `GET /health`
- `GET /ready`
- `GET /health/model`
- `GET /models`
- `GET /metrics`
- `POST /parse/image`

## Tests

```bash
python -m pytest tests/test_api.py
```
