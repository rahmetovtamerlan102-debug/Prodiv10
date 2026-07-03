FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir telethon python-telegram-bot aiohttp beautifulsoup4 lxml

COPY bot.py .

CMD ["python", "bot.py"]
