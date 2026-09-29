# Build context is the REPO ROOT (the backend now imports the shared llm_gateway package):
#     fly deploy --config backend/fly.toml --dockerfile backend/Dockerfile .
#     docker build -f backend/Dockerfile .
FROM python:3.11-slim

# Faster, cleaner Python in containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY backend/requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Shared provider layer (Anthropic direct / Bedrock / Ollama), importable as `llm_gateway`
# because it sits next to app.py in /app.
COPY llm_gateway/ ./llm_gateway/

# App source.
COPY backend/ .

# NO build-time index. The image used to run `python ingest.py` here, but production
# reads Qdrant CLOUD (QDRANT_URL / QDRANT_API_KEY are Fly secrets), so that local index
# was never read -- it only cost a ~130 MB model download per build and, worse, made a
# corpus change look deployed when it was not. After any corpus change, re-ingest
# against the live cluster:
#     fly ssh console -a yantra-chatbot -C "sh -c 'cd /app && python ingest.py'"
# Check which backend is live with:
#     fly ssh console -a yantra-chatbot -C "sh -c 'env | grep -i qdrant'"

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
