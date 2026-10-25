# ReverseAI — container image for hosting the web app.
#
# NOTE on the sandbox: bubblewrap needs unprivileged user namespaces, which many
# hosts disable. Without them, untrusted-code *execution* is refused (analysis,
# chat, research, cloning, and decompilation still work). For full sandboxed
# execution, run on a host that allows user namespaces (e.g. a VM/VPS), or run
# this container with the needed privileges. See docs/SECURITY.md.
FROM python:3.12-slim

# System deps: sandbox (bubblewrap), binutils (objdump/readelf), compiler,
# curl for health checks, and setpriv for dropping privileges at startup.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bubblewrap binutils gcc curl util-linux \
    && rm -rf /var/lib/apt/lists/*

# Optional analysis power-ups (small, pure-python). Ghidra/tesseract are added
# separately when you need decompilation/OCR.
RUN pip install --no-cache-dir capstone pyelftools lief || true

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir -e . || true

# Unprivileged runtime user. The data volume is chowned by the entrypoint.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin reverseai \
    && mkdir -p /data \
    && chown -R 10001:10001 /app /data
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV REVERSEAI_STORE=/data/jobs \
    HOME=/home/reverseai \
    PYTHONUNBUFFERED=1

VOLUME ["/data"]
EXPOSE 8077

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD curl -fsS "http://127.0.0.1:${PORT:-8077}/health" >/dev/null || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["sh", "-c", "python -m reverseai serve --host 0.0.0.0 --port ${PORT:-8077} --store ${REVERSEAI_STORE:-/data/jobs}"]
