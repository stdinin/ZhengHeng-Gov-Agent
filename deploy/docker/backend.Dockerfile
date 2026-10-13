ARG BASE_IMAGE=zhengheng-eval-runner:cpu
FROM ${BASE_IMAGE}

WORKDIR /workspace

# Reuse the locally verified V1.0 CPU dependency layer during V1.1 Compose
# validation. The current source is still copied into the resulting backend
# image; this avoids a second opaque PyTorch download during every role build.
COPY backend ./backend
COPY pyproject.toml README.md ./

EXPOSE 8000
ENTRYPOINT ["uvicorn"]
CMD ["backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
