FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends calibre && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

ENV CALIBRE_LIBRARY=/library
ENV CALIBRE_URL=http://localhost:8181
ENV QT_QPA_PLATFORM=offscreen

EXPOSE 3000

CMD ["python", "server.py"]
