# Front door for customers' panels (see router.py). Standard library only.
FROM python:3.12-slim
COPY deploy/router/router.py /app/router.py
USER nobody
ENV PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
CMD ["python", "/app/router.py"]
