FROM python:3.12-slim

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY patches/base.py /usr/local/lib/python3.12/site-packages/langchain_openai/chat_models/base.py

WORKDIR /app

COPY . .

# RUN useradd -m appuser
# USER appuser

EXPOSE 8000
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--reload"]
# CMD [ "uvicorn",  "app.main:app", "--reload"]