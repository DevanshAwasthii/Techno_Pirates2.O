# Future Online check (not included)

NexData's audit, interests and photo checks run locally. The teammate's
`app/intelligence_agent/` web-research implementation is deliberately not ported.
There is no Tavily/Brave lookup, web reader, public-image search or background
research in this build.

A future **Online check** must be a separate, disabled feature. Before every run,
show the destination/provider, exact proposed query or upload, likely disclosure,
retention policy and any cost. Let the user edit the preview and explicitly consent
to that run. Past consent must never authorize another run or background polling.

Send the minimum approved values only. Never automatically attach archives,
records, messages, cookies, local paths or photographs. Photo upload needs its own
explicit preview and consent. Keep API credentials outside reports and Git.
Cancellation and connection failure must preserve the offline audit. Label returned
claims as external, timestamp and cite them, and distinguish a search match from
verified exposure. Offer local deletion of queries and cached responses.

The optional OpenAI-compatible interpretation connector is a different feature:
it sends only compact taxonomy aggregates to loopback, or to an RFC1918 address
after the separate LAN setting and visible network warning. It performs no online
research and does not authorize any future Online check.
