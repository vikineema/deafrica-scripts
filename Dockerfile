FROM ghcr.io/osgeo/gdal:ubuntu-small-3.4.2 AS base

ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

ENV DEBIAN_FRONTEND=noninteractive \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8

RUN apt-get update \
    && apt-get install -y \
        # Developer convenience
        git \
        fish \
        wget \
        unzip \
        # Build tools\
        build-essential \
        python3-pip \
        python3-dev \
        # For Psycopg2
        libpq-dev \
        # Yaml parsing speedup, I think
        libyaml-dev \
        lsb-release \
        # For SSL
        ca-certificates \
        jq \
        # postgres
        postgresql-client \
        postgresql \
        # Build shapely
        libgeos-dev \
    # Cleanup
    && apt-get autoclean \
    && apt-get autoremove \
    && rm -rf /var/lib/{apt,dpkg,cache,log}

# Install yq
RUN wget https://github.com/mikefarah/yq/releases/download/v4.2.0/yq_linux_amd64.tar.gz -O - |\
tar xz && mv yq_linux_amd64 /usr/bin/yq

# Install AWS CLI.
WORKDIR /tmp
RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
RUN unzip awscliv2.zip
RUN ./aws/install

COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    --no-binary rasterio \
    --no-binary shapely \
    --no-binary fiona

RUN mkdir -p /code
WORKDIR /code

COPY . /code/

RUN pip install /code

CMD ["python", "--version"]

FROM base AS tests
RUN pip install --no-cache-dir -r /code/requirements-test.txt
