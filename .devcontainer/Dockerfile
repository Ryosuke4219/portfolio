# syntax=docker/dockerfile:1
FROM mcr.microsoft.com/devcontainers/python:3.11

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        git \
        build-essential \
        pkg-config \
        just \
    && rm -rf /var/lib/apt/lists/*

# uv provides a fast dependency resolver for Python projects.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir uv
