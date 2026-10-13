---
name: Yandex Maps checkout
description: Durable setup constraint for the marketplace pickup-point map.
---

The checkout pickup-point map uses the Yandex Maps JavaScript API and requires the
`YANDEX_MAPS_API_KEY` Replit Secret in shared/deployment environments. The UI should
keep consuming `/delivery/pvz`; the map layer is responsible for rendering, clustering,
provider filters, and selection, not for calling carrier APIs directly.

**Why:** The published checkout needs a stable Russian map experience without exposing
carrier credentials in browser code. Pickup addresses are operational customer data:
never show generated, sample, scraped, or cached-from-an-unverified-source locations.
When a provider catalog is unavailable, show that state and do not accept a point.

**How to apply:** When changing the checkout map, keep the key in Secrets, load Yandex
Maps only on checkout, and pass normalized, server-verified official carrier data from
the Flask endpoint. If the provider API is unavailable or credentials are missing, return
an empty catalog with a clear status rather than a mock fallback.