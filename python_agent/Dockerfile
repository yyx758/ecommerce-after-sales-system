FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt requirements-test.txt ./
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
RUN pip install --no-cache-dir --timeout 120 --retries 5 --index-url "$PIP_INDEX_URL" -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "after_sales_agent.interface.http_server"]
