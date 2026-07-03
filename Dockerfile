FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Установка telegram_gift_fetcher через git (если нужно)
RUN pip install --no-cache-dir git+https://github.com/CAPTHAIN/telegram_gift_fetcher.git

COPY bot.py .

CMD ["python", "bot.py"]
