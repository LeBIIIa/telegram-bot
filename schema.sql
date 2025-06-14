
CREATE TABLE IF NOT EXISTS applicants (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    age INTEGER NOT NULL,
    city TEXT NOT NULL,
    telegram_id BIGINT NOT NULL
);
