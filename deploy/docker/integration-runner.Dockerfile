FROM zhengheng-eval-runner:cpu

# The base image intentionally contains production dependencies only.  Keep
# pytest isolated to this acceptance-runner image rather than shipping it in
# the API runtime.
RUN python -m pip install "pytest>=8.3,<10.0" "pytest-asyncio>=0.25,<1.0"

WORKDIR /workspace

ENTRYPOINT ["python", "-u", "scripts/run_integration.py"]
