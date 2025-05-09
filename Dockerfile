FROM python:3.10-slim

# Рабочая директория
WORKDIR /app

# Скопировать зависимости и установить
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код
COPY . .

# Точка входа
CMD ["python", "main.py"]
