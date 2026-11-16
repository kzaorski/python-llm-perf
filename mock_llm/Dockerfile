FROM python:3.13.18-slim-trixie
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY mock_llm ./mock_llm
EXPOSE 8061
# a single asyncio process is enough: the mock only waits (asyncio.sleep), it does not compute
CMD ["uvicorn", "mock_llm.server:app", "--host", "0.0.0.0", "--port", "8061", "--no-access-log", "--timeout-keep-alive", "75"]
