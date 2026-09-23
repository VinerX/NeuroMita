FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY adapter.py .
ENV ADAPTER_CONFIG=/config/adapter.json
EXPOSE 8080
CMD ["python", "adapter.py"]
