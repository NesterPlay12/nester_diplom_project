---
name: Pickup delivery pricing
description: User-selected origin and pricing rule for pickup-point delivery.
---

For pickup orders, calculate distance from central Novomoskovsk to the selected pickup point and charge 50 RUB plus 0.4 RUB per kilometer. Use the city center coordinates as the origin; the distance is straight-line.

**Why:** the user chose Novomoskovsk as the origin and requested this formula.

**How to apply:** keep browser display and server-side order pricing consistent, and calculate the authoritative fee from the verified pickup point rather than trusting a submitted client amount.
