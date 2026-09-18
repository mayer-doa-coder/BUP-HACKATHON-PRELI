# GridWise — judge-facing service image.
#
# Design notes for whoever deploys this:
#
# * The base is pinned to a Debian release (bookworm), not a floating `slim`, so a rebuild next
#   week produces the same image. At release freeze, pin the digest as well and record it.
# * Dependencies install before the source is copied, so editing code does not re-download SciPy.
# * The build fails if the image cannot actually solve an LP and a MILP. A SciPy that imports but
#   cannot solve would turn every judged request into a 500, and that must not ship.
# * It runs as a non-root user and contains no credentials. Secrets are injected at run time by
#   the platform, never baked into a layer or passed as a build argument.
# * The listening port follows $PORT, because Azure (and most container platforms) assign one.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Dependency layer: changes only when requirements.txt changes.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application layer.
COPY app ./app
COPY scripts ./scripts
COPY public_cases ./public_cases

# Fail the build rather than the first judged request if the solver is not usable here.
RUN python scripts/verify_solver.py

# Non-root runtime. Created after the copies so it owns nothing it does not need to write.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin gridwise \
    && chown -R gridwise:gridwise /app
USER gridwise

EXPOSE 8000

# start-period covers interpreter startup; the probe itself is local and makes no provider call.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "scripts/healthcheck.py"]

# Shell form so ${PORT} is expanded at run time; `exec` keeps uvicorn as PID 1 so the platform's
# SIGTERM reaches it and in-flight requests can drain.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
