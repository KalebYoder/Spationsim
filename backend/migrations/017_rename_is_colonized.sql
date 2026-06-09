ALTER TABLE territories RENAME COLUMN is_colonized TO is_owned;
ALTER TABLE territories RENAME COLUMN colonized_at TO owned_at;
