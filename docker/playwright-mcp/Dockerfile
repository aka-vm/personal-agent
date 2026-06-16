FROM node:20-slim

RUN apt-get update && apt-get install -y \
    chromium \
    --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

ENV PLAYWRIGHT_BROWSERS_PATH=/usr/bin
ENV PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
ENV CHROME_PATH=/usr/bin/chromium

RUN npm install -g @playwright/mcp@latest

EXPOSE 3333

CMD ["npx", "@playwright/mcp", "--port", "3333", "--host", "0.0.0.0", "--browser", "chromium", "--executable-path", "/usr/bin/chromium", "--headless"]
