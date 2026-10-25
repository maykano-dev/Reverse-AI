# Deploying ReverseAI

ReverseAI is a single Python process serving the API and the UI. There is no
build step for the frontend and no database to provision.

## Render (one click)

1. Create a new Blueprint on Render and point it at this repository.
2. Set these secrets in the dashboard:
   - `DEEPSEEK_API_KEY`
   - `REVERSEAI_AUTH_TOKEN` (choose a long random value)
3. Optionally set `REVERSEAI_OCR_URL`, `REVERSEAI_SEARCH_URL`, or a budget.
4. Open the service URL. The UI asks for the access token on first load.

The blueprint creates a 1 GB disk at `/data` and sets
`REVERSEAI_ALLOWED_ROOTS=/data`. Uploads and artifacts live there.

### Sandbox on Render

Many PaaS hosts disable unprivileged user namespaces. Bubblewrap then cannot
run, and ReverseAI **refuses** untrusted execution instead of falling back to
the host. Analysis, chat, research, memory, routines, decompilation, and static
cloning still work. For full execution, deploy on a VM/VPS that allows user
namespaces, or run the container with the needed privileges.

## Docker

```bash
docker build -t reverseai .
docker run -d --name reverseai \
  -p 8077:8077 \
  -e DEEPSEEK_API_KEY=sk-... \
  -e REVERSEAI_AUTH_TOKEN=choose-a-token \
  -e REVERSEAI_MONTHLY_BUDGET=10 \
  -v reverseai-data:/data \
  reverseai
```

The image runs as user `10001` and the entrypoint fixes ownership of `/data`
before dropping privileges. `.env`, `.git`, job data, and caches are excluded
from the build context.

## A VM or bare metal

```bash
git clone https://github.com/maykano-dev/Reverse-AI.git
cd Reverse-AI
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
sudo scripts/setup_lab.sh          # bubblewrap, binutils, compiler, optional libs
export DEEPSEEK_API_KEY=sk-...
export REVERSEAI_AUTH_TOKEN=choose-a-token
python3 -m reverseai serve --host 127.0.0.1 --port 8077
```

Put a reverse proxy in front for TLS. Keep the app bound to loopback and let
the proxy forward to it. If you expose it directly, keep the token on.

## Optional services

| Service | Variable | Why |
|---|---|---|
| Unlimited-OCR (vLLM/SGLang) | `REVERSEAI_OCR_URL` | Long documents and PDFs |
| SearXNG | `REVERSEAI_SEARCH_URL` | Better research than DuckDuckGo HTML |
| Ghidra | `REVERSEAI_GHIDRA`, `REVERSEAI_JDK` | Decompilation |
| Qiling | `REVERSEAI_QILING_ROOTFS` | Foreign-platform emulation |

## Troubleshooting

- **"No isolating backend is available."** User namespaces are disabled. Run on
  a host that allows them, or accept analysis-only mode.
- **"This chat is no longer available."** The server lost the conversation
  state. Start a new chat; the old job record is still readable.
- **The UI asks for a token but you did not set one.** `REVERSEAI_AUTH_TOKEN`
  is set in the environment. Ask the operator, or unset it for local use.
- **Rendering a cloned site fails.** Headless rendering is off by default. Set
  `REVERSEAI_ALLOW_BROWSER_RENDER=1` only on a host you trust with untrusted
  pages.
- **Paid models stopped.** The monthly budget was reached. Raise
  `REVERSEAI_MONTHLY_BUDGET` or use a local model.
