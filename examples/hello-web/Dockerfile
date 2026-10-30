FROM python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY examples/hello-web/server.py /app/server.py
USER 10001:10001
EXPOSE 8080
CMD ["python", "/app/server.py"]
