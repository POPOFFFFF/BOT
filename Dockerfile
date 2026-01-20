FROM python:3.11-slim

# Рабочая папка внутри контейнера
WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --upgrade pip

RUN pip install --no-cache-dir -r requirements.txt
# Копируем код
COPY . .

# Запуск бота
CMD ["python", "arcady.py"]

