FROM pgvector/pgvector:pg16

COPY pg_bigm.tar.gz /tmp/pg_bigm.tar.gz

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
    && tar xzf /tmp/pg_bigm.tar.gz -C /tmp \
    && cd /tmp/pg_bigm-1.2-20240606 \
    && make USE_PGXS=1 \
    && make USE_PGXS=1 install \
    && rm -rf /tmp/pg_bigm* \
    && apt-get remove -y build-essential postgresql-server-dev-16 \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
