FROM node:24-alpine
WORKDIR /app
COPY . .
RUN node scripts/build-prototype.mjs
USER node
ENV TASTEBRIDGE_HOST=0.0.0.0 PORT=8080 API_BASE_URL=http://backend:9000
EXPOSE 8080
CMD ["node", "scripts/serve.mjs"]
