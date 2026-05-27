-- Add requested_by to diplomacy to track who sent a friend request.
-- Only meaningful when status = 'friend_pending'. NULL otherwise.
ALTER TABLE diplomacy ADD COLUMN IF NOT EXISTS requested_by INTEGER REFERENCES nations(id);
