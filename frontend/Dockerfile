# Static frontend served by unprivileged nginx; config.js is written at container start (K16).
# Build context: frontend/ (`docker build -t dap-frontend:dev frontend`).

FROM node:24.22.3-alpine@sha256:116b800c3754b440ee0aa3ed2f20f5bf3d99a554bfd9adeea09ea8017f6e85f5 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY public ./public
COPY src ./src
# The development config.js from public/ must not be served in place of the generated one.
RUN npm run build && rm dist/config.js && mkdir /runtime

FROM nginxinc/nginx-unprivileged:1.30.6-alpine@sha256:f5116ed4606f3eb015dd4a8e28cb9b351476dc0ad4bc6e9f93b19cec130cdf03
COPY nginx.conf /etc/nginx/nginx.conf
COPY --chmod=755 entrypoint.sh /entrypoint.sh
COPY --from=build /app/dist /usr/share/nginx/app
# Where entrypoint.sh writes config.js; mount an emptyDir here when the root filesystem is read-only.
COPY --from=build --chown=101:101 /runtime /usr/share/nginx/runtime
# uid 101 (nginx) from the base image.
USER 101
EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
