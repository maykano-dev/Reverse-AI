# ReverseAI — container image for hosting the web app.
#
# NOTE on the sandbox: bubblewrap needs unprivileged user namespaces, which many
# hosts disable. Without them, untrusted-code *execution* is refused (analysis,
# chat, and cloning still work). For full sandboxed execution, run on a host that
# allows user namespaces (e.g. a VM/VPS), or run this container with the needed
# privileges. See docs/SECURITY.md.
FROM python:3.12-slim

# System deps: sandbox (bubblewrap), binutils (objdump/readelf), compiler.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bubblewrap binutils gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Optional analysis power-ups (small, pure-python). Ghidra/tesseract are added
# separately when you need decompilation/OCR.
RUN pip install --no-cache-dir capstone pyelftools lief || true

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e . || true

ENV REVERSEAI_STORE=/data/jobs
VOLUME ["/data"]
EXPOSE 8077

# Bind 0.0.0.0 and honor the platform's $PORT. The model key is provided at
# runtime via env (DEEPSEEK_API_KEY, or REVERSEAI_PROVIDER + that key).
CMD ["sh", "-c", "python -m reverseai serve --host 0.0.0.0 --port ${PORT:-8077} --store ${REVERSEAI_STORE:-/data/jobs}"]
