FROM pgvector/pgvector:pg16

ARG PG_BIGM_VERSION=v1.2-20240606
ARG PG_BIGM_SHA256=69eabf7a6af19909fc8a33525768854b08c94929d7f9fa94fe31e737c04748ff

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        postgresql-server-dev-16 \
        curl \
    && curl -L "https://github.com/pgbigm/pg_bigm/archive/refs/tags/${PG_BIGM_VERSION}.tar.gz" \
        -o /tmp/pg_bigm.tar.gz \
    && echo "${PG_BIGM_SHA256}  /tmp/pg_bigm.tar.gz" | sha256sum -c - \
    && tar xzf /tmp/pg_bigm.tar.gz -C /tmp \
    && PG_BIGM_DIR="$(tar tzf /tmp/pg_bigm.tar.gz | head -1 | cut -d/ -f1)" \
    && cd "/tmp/${PG_BIGM_DIR}" \
    && make USE_PGXS=1 \
    && make USE_PGXS=1 install \
    && rm -rf /tmp/pg_bigm* \
    && apt-get remove -y build-essential postgresql-server-dev-16 curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

USER postgres
