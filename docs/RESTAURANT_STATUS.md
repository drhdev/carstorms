# Restaurant status: accuracy and operations

The dashboard restaurant card deliberately separates **a published schedule** from
**confirmation that a restaurant is operating today**. A website saying “daily” is
not evidence that the kitchen stayed open through a storm or power failure.

## Source order

1. **Verified same-day notice** — an operator checks an official restaurant post or
   calls the restaurant, then creates a `carstorm_notices` item. This overrides every
   automated source.
2. **Google Places API (New) `currentOpeningHours`** — includes the next seven days,
   special hours and `businessStatus`. It is refreshed with each dashboard build.
   It is the best structured source, but remains dependent on the restaurant updating
   its Google Business Profile.
3. **Official published schedule** — curated from the restaurant's own website. It
   is shown as “scheduled,” never “confirmed open.” Seasonal venues with no dependable
   schedule are shown as requiring a same-day check.
4. **Operational overlay** — active WAPA outages, thunderstorms, severe gusts and
   hazard warnings add a prominent call-ahead warning without claiming that every
   restaurant is closed.

The initial official schedules link to Skinny Legs, The Longboard, The Lime Inn,
Sun Dog Cafe, Ocean 362, Extra Virgin Bistro and Miss Lucy's. Each card includes the
official page and phone number so a user can verify directly.

## Enable current and special hours

Enable **Places API (New)** in a billing-enabled Google Cloud project, create a
server key restricted to that API and the deployment IP, then set:

```env
CARSTORMS_GOOGLE_PLACES_API_KEY=...
```

The worker uses Text Search with a St. John location bias and requests only place
identity, business status, current/special opening hours, official website, map and
phone and attribution fields. Google-derived content is not persisted or cached by
the restaurant integration; it is refreshed with the dashboard and visibly
attributed to Google Maps. A failure degrades to the published schedule without
failing the dashboard. Review Google Maps Platform's attribution, caching, Terms of
Use and Privacy Policy requirements before enabling the production key.

## Record a same-day closure or early close

Create an active `carstorm_notices` record with:

- `category`: `restaurant_status` or `restaurant_closure`
- `title`: include the exact venue name, for example `Skinny Legs closed today`
- `body`: the verified status and reason
- `url`: the official post used as evidence
- `starts_at` / `ends_at`: the validity window in AST
- `is_active`: `true`

Use `closed` or `not open` in the title/body for a closure. The card labels this tier
“Operator verified from official post or phone call.” Expire the notice at the end of
the affected service day. Social-network scraping is intentionally not used: access
is brittle and a missing post cannot prove a restaurant is open.

## Maintenance

- Review the curated official schedules monthly and before/after the seasonal closure
  period.
- Choose the dashboard refresh interval with Places API quota and billing in mind;
  seven curated venues currently produce seven Text Search requests per refresh.
- During tropical weather, assign an operator to review official posts/call priority
  venues and enter bounded same-day notices.
- Never translate a general island power outage into “restaurant closed”; show the
  operational warning and require venue-specific evidence.
