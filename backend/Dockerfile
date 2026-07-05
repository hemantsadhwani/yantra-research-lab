FROM python:3.11-slim

# Faster, cleaner Python in containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# App source.
COPY . .

# Build the vector index at image-build time so the container starts ready to serve.
# This downloads the fastembed ONNX model (~130 MB) once during the build.
# If your build environment has no network access, remove this line and run
#   python ingest.py
# as part of your container start command / entrypoint instead.
RUN python ingest.py

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
