FROM python:3.12-alpine AS base

ENV PYTHONUNBUFFERED=1
ENV OPENJPEG_VERSION=v2.5.4

RUN apk add --no-cache \
  cmake \
  gcc \
  git \
  jpeg-dev \
  make \
  musl-dev \
  tiff \
  tiff-dev \
  tiff-tools \
  zlib-dev

# Download and compile openjpeg
WORKDIR /tmp/openjpeg
RUN git clone https://github.com/uclouvain/openjpeg.git ./
RUN git checkout tags/${OPENJPEG_VERSION}
RUN cmake . && make && make install

WORKDIR /code
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src src

FROM base AS test
COPY .coveragerc ./
COPY tests tests
RUN pip install -r tests/test_requirements.txt

FROM base AS build
CMD [ "python", "-m", "src.create_derivatives" ]