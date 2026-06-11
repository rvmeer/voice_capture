CREATE TABLE IF NOT EXISTS participant (
    id serial PRIMARY KEY,
    name text UNIQUE,
    initials text,
    is_user boolean NOT NULL DEFAULT false
);

ALTER TABLE participant ADD COLUMN IF NOT EXISTS initials text;
ALTER TABLE participant ADD COLUMN IF NOT EXISTS is_user boolean NOT NULL DEFAULT false;
UPDATE participant SET is_user = true WHERE lower(name) = 'ralf van meer';
