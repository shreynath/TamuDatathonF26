# Build from the complete TamuDatathonF26 checkout AFTER copying this overlay.
FROM python:3.13-slim
WORKDIR /app
COPY . /app
EXPOSE 8765
ENV PYTHONUNBUFFERED=1 PITBOSS_HOST=0.0.0.0 PITBOSS_PORT=8765
# Container port is internal unless deliberately published. Place behind a TLS reverse proxy.
CMD ["python","apps/api/server.py"]
