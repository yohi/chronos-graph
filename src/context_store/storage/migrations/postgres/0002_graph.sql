-- Graph schema for PostgreSQL

CREATE TABLE memory_nodes (
    id       TEXT PRIMARY KEY,
    metadata JSONB NOT NULL DEFAULT '{}'
);

CREATE TABLE memory_edges (
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    props     JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (from_id, to_id, edge_type),
    CONSTRAINT fk_from_node FOREIGN KEY(from_id) REFERENCES memory_nodes(id) ON DELETE CASCADE,
    CONSTRAINT fk_to_node FOREIGN KEY(to_id) REFERENCES memory_nodes(id) ON DELETE CASCADE
);

CREATE INDEX idx_memory_edges_to_id ON memory_edges (to_id);
CREATE INDEX idx_memory_edges_type  ON memory_edges (edge_type);
