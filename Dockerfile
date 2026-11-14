# XML Proofreader as a container.
#
#   docker build -t xml-proofread .          # the app
#   docker build --target test .             # run the tests (no API key needed)
#   docker run --rm --env-file .env -v "$PWD:/data" xml-proofread \
#     examples/sample_input.xml --lang en-US --style-guide examples/Style_Guide.docx

# ---------- test stage: runs every test with the fake AI while building ----------
FROM python:3.12-slim AS test
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
# Use the image's Python (never download one) and copy packages instead of linking them.
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
# Dependencies first, so this layer is reused when only the code changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
RUN uv run --no-sync pytest -q

# ---------- runtime stage (the default): only what the program needs ----------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
ENV PATH="/app/.venv/bin:$PATH"

# Don't run as root.
RUN useradd --create-home app
USER app

# Mount your folder at /data: paths work as they do locally, and the
# .corrected.xml output is written next to the input on your machine.
WORKDIR /data
ENTRYPOINT ["python", "/app/main.py"]
