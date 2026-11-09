# ExamFlow AI - single container, standard library only.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000 \
    EXAMFLOW_DB=/data/examflow.db

WORKDIR /app
COPY server ./server
COPY static ./static
COPY README.md ./

# /data is the only path that needs to survive a restart
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=4s --start-period=10s \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["python3", "server/app.py"]
