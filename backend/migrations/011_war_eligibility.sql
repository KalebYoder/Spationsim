-- Track the highest-ever colonized territory count per nation.
-- Used for the 3:1 ratio war-eligibility gate so the field cannot be
-- gamed by voluntarily abandoning territories before declaring war.
ALTER TABLE nations ADD COLUMN max_colonized_territory_count INTEGER NOT NULL DEFAULT 0;

UPDATE nations
SET max_colonized_territory_count = (
    SELECT COUNT(*)
    FROM territories
    WHERE nation_id = nations.id
      AND is_colonized = true
);
