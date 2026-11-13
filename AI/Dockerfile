FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt ./
# CPU wheels avoid downloading CUDA libraries for the default development service.
RUN pip install --no-cache-dir torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu \
  && pip install --no-cache-dir -r requirements.txt
COPY advisor ./advisor
COPY data ./data
COPY evals/secops.json ./evals/secops.json
RUN useradd --create-home advisor && mkdir -p artifacts && chown advisor:advisor artifacts
USER advisor
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health/live')"
CMD ["uvicorn", "advisor.app:app", "--host", "0.0.0.0", "--port", "8000"]
