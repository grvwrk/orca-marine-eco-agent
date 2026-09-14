FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
COPY agents ./agents
COPY orchestration ./orchestration
COPY ingestion ./ingestion
COPY llm ./llm
RUN pip install --no-cache-dir -e .[live]

EXPOSE 8000
CMD ["uvicorn", "orca.api.main:app", "--host", "0.0.0.0", "--port", "8000"]