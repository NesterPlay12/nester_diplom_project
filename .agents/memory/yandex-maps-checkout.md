---
name: Yandex Maps checkout
description: Durable setup constraint for the marketplace pickup-point map.
---

The checkout pickup-point map uses the Yandex Maps JavaScript API and requires the
`YANDEX_MAPS_API_KEY` Replit Secret in shared/deployment environments. The UI should
keep consuming `/delivery/pvz`; the map layer is responsible for rendering, clustering,
provider filters, and selection, not for calling carrier APIs directly.

**Why:** The published checkout needs a stable Russian map experience without exposing
carrier credentials in browser code. Keeping carrier data server-side also preserves the
fallback behavior when an external provider is unavailable.

**How to apply:** When changing the checkout map, keep the key in Secrets, load Yandex
Maps only on checkout, and pass normalized PVZ data from the Flask endpoint.