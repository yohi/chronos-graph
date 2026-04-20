-- Graph schema for SQLite

CREATE TABLE IF NOT EXISTS memory_nodes (
    id       TEXT PRIMARY KEY,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS memory_edges (
    from_id   TEXT NOT NULL,
    to_id     TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    props     TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (from_id, to_id, edge_type),
    FOREIGN KEY(from_id) REFERENCES memory_nodes(id) ON DELETE CASCADE,
    FOREIGN KEY(to_id) REFERENCES memory_nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS memory_edges_to_idx ON memory_edges (to_id);
CREATE INDEX IF NOT EXISTS memory_edges_type_idx ON memory_edges (edge_type);
