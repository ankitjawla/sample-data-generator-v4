# Branding assets (optional)

The app header shows a brand on the left and right of the title. By default it
renders text wordmarks (see `BRAND_LEFT` / `BRAND_RIGHT` near the top of `app.py`,
also overridable via the `SDG_BRAND_LEFT` / `SDG_BRAND_RIGHT` env vars).

To use **real logos**, drop image files here named:

- `capgemini.png` (or `.svg` / `.jpg` / `.webp`) — shown on the **left**
- `barclays.png` (or `.svg` / `.jpg` / `.webp`) — shown on the **right**

They're embedded into the page (base64), no hosting needed. Height ≈ 40px.
Set a brand constant to `""` to hide that side.

> These names ship in a public repo. Edit the constants in `app.py` to use your
> own company / client, or blank them out.
