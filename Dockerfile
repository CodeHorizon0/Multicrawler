FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends     ca-certificates     fonts-liberation     libasound2     libatk-bridge2.0-0     libatk1.0-0     libcairo2     libcups2     libdbus-1-3     libexpat1     libfontconfig1     libgcc-s1     libglib2.0-0     libgtk-3-0     libnspr4     libnss3     libpango-1.0-0     libx11-6     libx11-xcb1     libxcb1     libxcomposite1     libxdamage1     libxext6     libxfixes3     libxkbcommon0     libxrandr2     xdg-utils     && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt && playwright install --with-deps chromium

COPY . .

VOLUME ["/data"]
ENTRYPOINT ["python", "-m", "multicrawler"]
