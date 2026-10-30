FROM mcr.microsoft.com/playwright:v1.64.1-noble
WORKDIR /work
COPY tests/e2e/package.json tests/e2e/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY tests/e2e ./
CMD ["npm", "test"]
