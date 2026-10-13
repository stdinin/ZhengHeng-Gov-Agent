FROM python:3.12-slim

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

WORKDIR /opt/zhengheng

COPY pyproject.toml README.md ./
COPY backend ./backend
COPY scripts ./scripts

RUN python -m pip install --index-url https://download.pytorch.org/whl/cpu torch \
    && python -m pip install .

WORKDIR /workspace

ENTRYPOINT ["python", "-u", "scripts/run_public_eval.py"]
