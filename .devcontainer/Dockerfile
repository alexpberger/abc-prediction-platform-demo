FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# Install Node in the image instead of with a Dev Container Feature.
# Feature install is fetched by Cursor's host Node process, which fails
# certificate checks behind the local TLS-inspecting proxy. Docker can
# reach nodejs.org, so the download happens at image build time.
ARG NODE_VERSION=22.23.3
ARG NODE_SHA256=df450af89261115ef9f9e3830c3eeb2cc9213b63c720b1af623cb5dcbe2e02de

RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" -o /tmp/node.tar.xz \
    && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
    && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
    && rm /tmp/node.tar.xz \
    && node --version \
    && npm --version
