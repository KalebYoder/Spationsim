# Manual UI/UX Test Plan

Run these tests in order — each section builds on the state left by the previous one. Two accounts are needed for multiplayer tests (marked **[2-player]**). Expected outcomes are in _italics_.

---

## 1. Authentication

### 1.1 Register
1. Navigate to `/register`
2. Submit the form empty — _error messages appear for all required fields_
3. Submit with a password shorter than 8 characters — _password error appears_
4. Submit with an invalid email format — _email error appears_
5. Fill in valid username, email, and password — _redirect to `/create-nation`_
6. Confirm the "Log in" link navigates to `/login`

### 1.2 Login
1. Navigate to `/login`
2. Submit with wrong credentials — _error message appears, button re-enables_
3. Submit with correct credentials — _redirect to `/` (home)_
4. Confirm the "Register" link navigates to `/register`

### 1.3 Protected route redirect
1. While logged out, navigate to `/` — _redirect to `/login`_
2. Log in, then navigate to `/login` directly — _redirect to `/`_

### 1.4 Logout
1. Click "Log out" in sidebar footer — _redirect to `/login`, sidebar gone_
2. Navigate to `/` while logged out — _redirect to `/login`_

---

## 2. Nation Creation Wizard

### 2.1 Step 1 — Identity
1. Arrive at `/create-nation` after fresh registration
2. Click "Next" with no inputs — _button should be disabled or validation fires_
3. Enter a nation name under 3 characters — _error appears_
4. Enter a valid nation name and currency name
5. Change the color picker — _color swatch and hex code update live_
6. Click "Next: Choose Home System" — _advance to Step 2_

### 2.2 Step 2 — Map Picker
1. Confirm the hex map renders with color-coded territories
2. Hover over a territory — _tooltip shows coordinates, richness values, distance_
3. Try to click a void territory (dark node) — _nothing happens, no selection_
4. Click a valid (non-void) unclaimed territory — _it highlights with white stroke, info panel populates below the map_
5. Confirm the "Home Planet Name" field auto-focuses
6. Try clicking "Next" with no planet name — _button stays disabled_
7. Enter a planet name — _"Next" button enables_
8. Click "← Back" — _returns to Step 1 with previous values preserved_
9. Re-advance to Step 2, re-select territory, re-enter planet name
10. Click "Next: Confirm" — _advance to Step 3_

### 2.3 Step 3 — Confirmation
1. Confirm all entered values are displayed correctly (nation name, currency, color, planet name, coordinates, richness)
2. Click "← Back" — _returns to Step 2 with selections intact_
3. Re-advance and click "Launch Nation" — _button shows "Launching…" during submit_
4. After success — _redirect to `/`_

### 2.4 Already has nation
1. Log in with an account that already has a nation and navigate to `/create-nation` — _redirect to `/`_

---

## 3. Sidebar Navigation

1. Confirm all links are present: Nation, Economy, Facilities, Military, Probes, Planets, Map, Diplomacy, Friends, Trade, Mail, Event Log
2. Click each link — _correct page loads, active link has amber text and left border highlight_
3. Confirm the nation name and flag color dot appear in the sidebar header
4. Confirm the username appears in the sidebar footer

---

## 4. Home (Nation Overview)

1. Verify all resource stat cards display: Minerals, Fuel, Population (unassigned), Territories, Military units
2. Verify Power stat cards display: Military Strength, Industrial Strength
3. Confirm "Active Alerts" section is present (empty state acceptable)
4. Confirm "Recent Events" section is present (empty state acceptable)

### 4.1 Vacation Mode
1. Click "Enter Vacation" — _button shows loading state, then status badge changes to "Active"_
2. Confirm the exit cooldown countdown appears
3. While in vacation, attempt to navigate away and return — _status persists_
4. Wait for or mock the cooldown expiry; click "Exit Vacation" — _status returns to "Inactive"_

---

## 5. Economy

1. Navigate to `/economy`
2. Confirm Stockpiles cards show current minerals and fuel with "+X per tick" sub-text
3. Confirm the "Next Tick" countdown counts down in real time (HH:MM:SS)
4. Confirm Population cards show Total, Assigned, and Unassigned values
5. If territories exist, confirm the Production table has rows with colored values (amber minerals, teal fuel, purple pop cap)
6. Click a territory row — _navigates to `/planets` or highlights the territory_

---

## 6. Facilities

### 6.1 Building a facility
1. Navigate to `/facilities`
2. In the Build Form, select a territory and facility type
3. Confirm cost and build time update to match the selection
4. If resources are insufficient, confirm the affordability indicator turns red and "Build" is disabled
5. With sufficient resources, click "Build" — _button shows loading state; on success, facility appears in the table with "Building" status_

### 6.2 Facilities table
1. Confirm columns: Type, Territory, Status, Completes, Level, Actions
2. Click a column header — _table sorts by that column; arrow indicator changes_
3. Click the same header again — _sort direction reverses_
4. Confirm "Building" status shows a countdown in "Xh Ym" format
5. Confirm "Active" facility shows a "Demolish" button; "Building" facility does not
6. Click "Demolish" on an active facility — _facility changes to "Demolishing" status; footer note about 25% refund is visible_

---

## 7. Military

### 7.1 Manufacture starfighters
1. Navigate to `/military`
2. Confirm stat cards show Total, Stationed, In Transit, Colony Ships, Minerals, Fuel
3. Click "Manufacture" button — _form appears with territory and quantity inputs_
4. Select a territory without a shipyard — _"Manufacture" disabled or message shown_
5. Select a territory with a shipyard and enter a quantity
6. Confirm cost breakdown updates correctly
7. Click "Manufacture" — _success: units appear in stationed fleets table_
8. Click "Cancel" — _form closes_

### 7.2 Stationed fleets table
1. Confirm territory name, fighter count, and action buttons appear per row
2. Confirm unclaimed territories show an "Unclaimed" badge and "Claim Territory" button
3. Click "Claim Territory" on an unclaimed territory — _territory becomes claimed, badge disappears_

### 7.3 Colony ships
1. Toggle the Build Colony Ship form — _form appears with territory dropdown and cost breakdown_
2. Build a colony ship — _it appears in the Stationed Colony Ships table_
3. Expand a colony ship row's actions panel:
   - Click "Load" — _number input appears with max = 100 − current cargo; confirm and cancel work_
   - Click "Unload" — _number input appears; confirm and cancel work_
   - Click "Deploy" — _territory dropdown appears; confirm dispatches the ship_
4. Confirm a dispatched colony ship appears in "In Transit Colony Ships" with ETA

---

## 8. Probes

### 8.1 Manufacture probes
1. Navigate to `/probes`
2. Click "Manufacture Probes" — _form appears with quantity input and cost display_
3. Enter a quantity and click "Manufacture" — _reserve count increases_
4. Click "Cancel" — _form closes_

### 8.2 Launch probe — interactive map
1. Click "Launch Probe" — _SVG map appears with color-coded territories_
2. Verify legend colors: teal (your territories), blue (in-range unclaimed), purple (in-range enemy), dark (out of range)
3. Click one of your territories as origin — _origin highlights white_
4. Click a destination in range — _destination highlights amber; travel time displays_
5. Try clicking an out-of-range territory — _no selection or error_
6. Click "Launch" — _probe appears in Active Probes table with "In Transit" status and ETA_
7. Click "Cancel" — _form closes without sending_

### 8.3 Active probes and intelligence
1. Confirm Active Probes table shows: Probe #, From, Destination, ETA, Status
2. After a probe arrives, confirm a new row in "Your Intelligence" table
3. Confirm intelligence rows show: coordinates, mineral/fuel richness, scouted time (relative), status ("Unclaimed" or "Colonized by X")

---

## 9. Planets

1. Navigate to `/planets`
2. Confirm home territory is sorted first with a "Home" badge
3. Confirm each card shows: distance, mineral richness (2 decimal places), fuel richness
4. Click a card header — _card expands to show Population, Facilities, and Military sections_
5. Click again — _card collapses_

### 9.1 Rename territory
1. Click the pencil icon (✎) on any territory card — _text input appears, auto-focused_
2. Clear the field and try to save — _error appears or save is prevented_
3. Enter a new name and click Save — _header updates with new name_
4. Press Escape or Cancel — _input closes without saving_

---

## 10. Map View

1. Navigate to `/map`
2. Confirm the legend is visible with all color explanations
3. Hover over your territory — _tooltip shows coordinates, nation name, fighters if any_
4. Hover over an unclaimed territory — _tooltip shows "Unclaimed", richness values if probed_
5. Hover over an enemy territory — _tooltip shows nation name (colored by diplo status)_
6. Verify amber dot indicators appear on territories with stationed fighters

### 10.1 Deploy fleet — two-click flow
1. Click one of your territories with stationed fighters — _deploy panel opens on the right_
2. Confirm the panel shows "From" territory and awaits destination
3. Click a reachable destination — _"To" field fills, travel time and quantity input appear_
4. Try setting quantity above your available fighters — _"Send Fleet" stays disabled or shows error_
5. Set a valid quantity and click "Send Fleet" — _success message appears in teal with "Dismiss" button_
6. Confirm the dispatched fleet appears in Military → In Transit table
7. Click "Dismiss" — _success message disappears_
8. Click "Cancel" in the deploy panel — _panel closes without sending_

### 10.2 Unreachable destination (pathfinding)
1. Identify a territory blocked by a solid wall of void tiles or enemy territory
2. Attempt to send a fleet there — _409 error: "Destination is not reachable from origin"_

### 10.3 Nation info panel **[2-player]**
1. Click an enemy territory (not in deploy mode) — _nation info panel appears_
2. Confirm it shows the nation name, status badge, and "Declare War" button
3. Click the close (✕) button — _panel closes_

---

## 11. Diplomacy

1. Navigate to `/diplomacy`
2. Confirm the Relations table appears (empty state acceptable if all neutral)
3. If relationships exist, confirm status badges are color-coded: War (red), Friendly (green), Neutral (grey)
4. Click a nation row — _navigates to that nation's profile page_
5. Confirm the Alliances section is visible but grayed with a "Post-Beta" badge

---

## 12. Friends **[2-player]**

1. Navigate to `/friends`
2. Confirm three sections: Incoming Requests, Sent Requests, Friends

### 12.1 Send a friend request
1. Navigate to the other player's nation profile (`/nations/{id}`)
2. Click "Add to friends list" — _button changes to "Request Sent" + "Cancel"_
3. In the other player's `/friends` — _request appears in Incoming Requests table_

### 12.2 Accept / refuse
1. Other player clicks "Accept" — _both players see each other in Friends section with "Since" date_
2. For a separate test: other player clicks "Refuse" — _request disappears from both views_

### 12.3 Remove friend
1. Click "Remove" next to a friend — _they move out of the Friends list_

### 12.4 Cancel outgoing request
1. Send a request, then click "Cancel" in Sent Requests — _request disappears_

---

## 13. Trade **[2-player]**

### 13.1 Propose trade
1. Navigate to `/trade`
2. In the "Trade with" dropdown, select the other nation
3. Confirm route status indicator shows "has route" or explains why there is none
4. Enter values in the offer/request fields (confirm max labels are accurate)
5. Click "Propose Trade" — _trade appears in Outgoing Offers for you and Incoming Offers for them_

### 13.2 Accept / reject
1. Other player views incoming trade and clicks "Accept" — _5-second countdown timer appears_
2. After countdown, confirm the trade completes and resources transfer
3. For a separate test: click "Reject" — _trade disappears from both views_

### 13.3 Edit terms
1. Click "Edit terms" on an outgoing trade — _inline edit form expands_
2. Modify values and click "Save" — _terms update in the table_
3. Click "Cancel" — _form closes with original values_

### 13.4 Cancel outgoing trade
1. Click "Cancel" on your outgoing trade — _trade removed from both views_

---

## 14. Mail **[2-player]**

### 14.1 Compose and send
1. Navigate to `/mail`
2. Click "Compose" — _form appears with recipient dropdown, subject, and body fields_
3. Select a recipient, enter subject and body
4. Click "Send" — _message appears in Outbox; recipient sees it in Inbox with an unread dot_
5. Click "Cancel" — _form closes_

### 14.2 Inbox and reading
1. Switch to "Inbox" tab — _unread count badge shows on tab_
2. Click an unread message row — _message expands with full content, sender info, and timestamp; bold text and dot disappear_
3. Click again — _message collapses_

### 14.3 Reply flow
1. Expand a received message and click "Reply" — _compose form opens with recipient and subject pre-filled_
2. Confirm pre-filled subject has "Re:" prefix
3. Send the reply — _appears in Outbox_

### 14.4 Delete message
1. Click the ✕ delete button on a message row — _message removed; other rows unaffected_

### 14.5 Sidebar badge
1. Receive a new mail — _amber badge count in sidebar increments within ~30 seconds_
2. Read the mail — _badge count decrements_

---

## 15. Event Log

1. Navigate to `/log`
2. Confirm entries are grouped by tick with timestamps
3. Confirm resource deltas (minerals, fuel, currency, population) show with green/red coloring
4. Confirm hostile events (enemy fleet arrived, probe destroyed) render with red text and red left border
5. Confirm non-hostile events use normal text and border

---

## 16. Nation Profile

1. Navigate to `/nations/{own-id}` — _"Your Nation" badge appears; no war/friend buttons_
2. Confirm flag color swatch, nation name, currency name, territory count, and power stats display

### 16.1 War declaration **[2-player]**
1. Navigate to the other player's profile
2. Click "Declare War" — _confirmation modal appears with cancel and confirm buttons_
3. Click "Cancel" — _modal closes, no war declared_
4. Click "Declare War" again, then confirm — _"War Declared" badge + countdown appears_
5. Confirm the other player's profile now shows "At War" status
6. Confirm the "Propose Trade" button is hidden when at war

### 16.2 Friend request from profile
1. Click "Add to friends list" — _button changes to "Request Sent"_
2. The other player accepts — _button changes to "Remove from friends list"_

### 16.3 Vacation mode alert
1. Put the other player's account in vacation mode
2. View their profile — _vacation alert is displayed_

---

## 17. Chat Window **[2-player]**

1. Confirm the chat widget is visible (fixed bottom-right) on all game pages
2. Click the "Chat" header — _window expands_
3. Click again — _window collapses_

### 17.1 Public channels
1. Switch to "General" tab and send a message — _message appears with your nation name in teal_
2. Other player views General — _your message appears with their name in amber_
3. Switch to "Trade" tab and repeat

### 17.2 Direct messages
1. Click "+ DM" — _nation picker dropdown appears_
2. Click the other nation — _DM tab opens_
3. Send a message — _other player gets an unread badge on the Chat widget and their DM tab_
4. Other player opens the DM tab — _badge clears_
5. Close the DM tab (× button) — _tab disappears_

### 17.3 Unread badge
1. While chat is collapsed and a new message arrives — _amber badge count appears on the "Chat" header_

---

## 18. Cross-Cutting Checks

### 18.1 Loading states
1. On any form, observe the submit button during a slow request — _button text changes to "…ing" variant and is disabled during the request_

### 18.2 Error recovery
1. Trigger an API error (e.g., disconnect backend briefly) and submit any form — _error message appears inline; form is still usable after_

### 18.3 Countdown timers
1. On Economy page, verify the "Next Tick" countdown decrements every second
2. On Facilities page, verify in-progress build countdowns update
3. On Trade page, verify the 5-second confirmation cooldown counts down accurately

### 18.4 Number formatting
1. On any resource display, confirm large numbers use thousands separators (e.g., 1,234,567)
2. Confirm richness values display to 2 decimal places

### 18.5 Responsive layout (basic sanity)
1. Resize the browser window to a narrow width — _sidebar and content don't overlap catastrophically_

### 18.6 Stale session
1. Let the session expire or manually clear the auth cookie
2. Navigate to any game page — _redirect to `/login`_
