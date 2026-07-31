FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ca-certificates xvfb xauth fonts-liberation fonts-noto-core \
    fonts-noto-cjk fonts-noto-color-emoji fontconfig \
    && wget -q https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb \
    && (dpkg -i google-chrome-stable_current_amd64.deb || apt-get -f install -y) \
    && rm -rf /var/lib/apt/lists/* google-chrome-stable_current_amd64.deb \
    && fc-cache -f
WORKDIR /app
COPY requirements.txt pyproject.toml ./
COPY aurora ./aurora
COPY aurora.py config.yaml ./
RUN pip install --no-cache-dir .
ENTRYPOINT ["xvfb-run", "-a", "--server-args=-screen 0 1920x1080x24", "python", "aurora.py"]
CMD ["run-once"]

