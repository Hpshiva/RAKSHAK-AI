FROM python:3.9-slim

WORKDIR /app

# Install system dependencies required by OpenCV and MediaPipe
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all your code into the container
COPY . .

# Hugging Face requires web apps to run on port 7860
EXPOSE 7860

# Run the app using gunicorn for better stability and multiple threads
CMD ["gunicorn", "-b", "0.0.0.0:7860", "--threads", "4", "--timeout", "120", "app:app"]
