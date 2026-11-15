FROM mcr.microsoft.com/playwright/python:v1.65.2-noble
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
RUN useradd -m -u 10001 agent && mkdir -p /app/runtime && chown -R agent:agent /app/runtime
USER agent
ENV PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765", "--no-access-log", "--limit-concurrency", "100", "--timeout-keep-alive", "5"]
