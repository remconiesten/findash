FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt requirements-qdrant.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-qdrant.txt
COPY app ./app
COPY sql ./sql
COPY run.py ./run.py

EXPOSE 8088
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8088/health')"

CMD ["python", "run.py"]
