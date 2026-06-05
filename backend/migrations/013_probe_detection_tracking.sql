-- Track the last nation a probe was detected in so we only fire
-- foreign_probe_detected on first entry, not every tick it remains.
ALTER TABLE probes ADD COLUMN last_detected_nation_id INTEGER REFERENCES nations(id);
