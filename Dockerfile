FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY ferry/ ferry/
RUN pip install --no-cache-dir .

EXPOSE 8080
CMD ["ferry-hub", "--dir", "/data", "--host", "0.0.0.0", "--port", "8080"]
