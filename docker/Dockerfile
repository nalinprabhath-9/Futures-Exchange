FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# copy package
COPY node/ /app/node/

ENV PYTHONUNBUFFERED=1
ENV DB_PATH=/data/chain.db
ENV PYTHONPATH=/app

EXPOSE 5000

CMD ["python", "-u", "-m", "node.app"]