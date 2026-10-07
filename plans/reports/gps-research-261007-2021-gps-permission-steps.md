# GPS permission steps for websites (iOS Safari, iOS Chrome, Android Chrome) — 2026-10-07

Task: verify current (2025–2026) user steps to allow a website (e.g. https://tingting.vip) to use GPS location, for a Vietnamese worker audience, so the chatbot can quote them verbatim.

Key structural fact: **two gates** must both allow before a page gets a GPS fix:
1. the browser's per-site permission (the site prompt / site settings), and
2. the OS-level location switch (iOS Location Services for the browser app; Android system Location + Chrome's app permission).

If gate 2 is off, the site-prompt path is irrelevant — quote the Settings path instead.

---

## 1. iOS Safari (iPhone)

### (a) Address-bar path — works even after tapping "Don't Allow"
1. Open the site in Safari (e.g. https://tingting.vip).
2. Tap the **aA / AA** icon in the address bar ("aA" on iOS 15–17; "AA" on iOS 18/26 — same page menu).
3. Tap **Website Settings**.
4. Scroll to **Location** → set **Ask** or **Allow**.
5. Reload the page → the site prompt reappears → tap **Allow** (choices like "This Time Only" / "Always Allow").

### (b) Settings → Safari default for websites
- iOS 18/26: **Settings → Apps → Safari** (iOS ≤17: **Settings → Safari** directly). Apple's own article now quotes "Go to Settings, tap Apps, then select Safari".
- Scroll to **Settings for Websites** → **Location** → **Ask / Deny / Allow** (default for sites that haven't asked yet).
- This is a default, **not** a per-site list.

### (c) Location Services master toggle + per-app
1. **Settings → Privacy & Security → Location Services** → confirm the master toggle is ON.
2. In the app list, tap **Safari** (websites that have asked appear under **Safari Websites**) → **Ask Next Time Or When I Share** or **While Using the App**.
3. Turn on **Precise Location** if the row exists.
Per-app options are: **Never / Ask Next Time Or When I Share / While Using the App / Always**.

### iOS per-site reset — one-line answer
Per-site location is reset in exactly two places: on the site itself via **aA → Website Settings → Location**, or **Settings → Privacy & Security → Location Services → Safari Websites → [site]** (Never / Ask Next Time / While Using). **Not** "Settings → Safari → Website Data" — that list is cookies/storage only. Nuclear option: **Settings → General → Transfer or Reset iPhone → Reset → Reset Location & Privacy** (resets every app and website; they re-ask on next use).

---

## 2. iOS Chrome

Chrome on iOS follows the **iOS system permission** for app-level access; it has **no per-site permission manager** (no Android-style Site settings). It has only the in-page prompt plus a default choice in Content Settings.

1. Open the site in Chrome → tap **Allow** on Chrome's location prompt; if the iOS system alert "Chrome Would Like to Use Your Current Location" appears, tap **Allow**.
2. If blocked before: iPhone **Settings → (Apps →) Chrome → Location → While Using the App** (iOS 18+ groups Chrome under Settings → Apps).
3. In-Chrome default (recovers a site dismissed with Block): Chrome **⋯ More → Settings → Content Settings → Location → Ask**, then reload the site.
4. Master toggle same as Safari: **Settings → Privacy & Security → Location Services → Chrome**.

So: yes, Chrome iOS has a small own UI (Content Settings default), but per-site control is effectively delegated to the iOS system + the reloadable in-page prompt.

---

## 3. Android Chrome (grant location)

### Path A — on the site (primary, shortest)
1. Open the site in Chrome.
2. Tap **View site information** — the lock icon (Chrome ≤116) or sliders/"tune" icon (Chrome 117+) to the **left** of the address bar.
3. Tap **Permissions** → **Location** → **Allow this time** or **Allow while visiting the site**.

### Path B — Chrome settings
1. Chrome **⋮ (Tuỳ chọn khác) → Settings (Cài đặt)**.
2. Under "Advanced": **Site settings (Cài đặt trang web)** → **Location (Vị trí)** → set default to **Ask**; individual sites under **Allowed (Được phép)** / **Not allowed (Không được phép)**, tap the ⋮ beside a site to change it.

### Path C — Android system app permission
1. Phone **Settings → Apps → Chrome → Permissions → Location → Allow only while using the app**.
2. Equivalent on some devices: **Settings → Location → App permissions → Chrome**.
Chrome itself must hold this Android permission or geolocation never works, regardless of site settings.

---

## 4. Android Chrome (reset a previously blocked site)

1. On the site: tap the **ⓘ / lock / tune** icon left of the address bar → **Permissions** → **Location** → **Allow** — or tap **Reset permissions** to clear all custom choices for that site (returns it to Chrome defaults).
2. If the prompt no longer appears: **⋮ → Settings → Site settings → All sites → [site] → Location → Allow/Ask**.

---

## Master-toggle-off: what the user actually sees

- **iOS, Location Services OFF** (Apple: "apps can't use your location"): the site's prompt may still appear, but the fix never resolves — the page gets a geolocation error (`PERMISSION_DENIED`, code 1) and iOS can surface a system alert like "Turn On Location Services to Allow [site] to Access Your Location". The website cannot fix this; only Settings → Privacy & Security → Location Services can.
- **Android, system Location OFF**: Chrome's site prompt never completes (per user reports it may not appear at all); geolocation fails with `POSITION_UNAVAILABLE` (code 2) because the providers are off. Fix is system-level: Quick Settings **Location** tile ON, plus Settings → Location → App permissions → Chrome.
- **Chatbot-script implication:** when a turn fails with a location error *after* the user already allowed the site, quote the master-toggle path (iOS: Privacy & Security → Location Services; Android: Quick Settings Location tile), not the site-permission path.

---

## Vietnamese UI labels

Verified verbatim from Google's Vietnamese Chrome help (142065, hl=vi): **"Tuỳ chọn khác"** (More ⋮), **"Cài đặt"** (Settings), **"Cài đặt trang web"** (Site settings), **"Vị trí"** (Location), **"Cho phép"** (Allow), **"Được phép"** / **"Không được phép"** (Allowed / Not allowed), **"Xem thông tin trang web"** (View site information), **"Quyền"** (Permissions).

Apple Vietnamese localization (standard VN iOS wording, not fetched verbatim from Apple): **"Cài đặt"**, **"Ứng dụng"**, **"Quyền riêng tư & Bảo mật"**, **"Dịch vụ định vị"**, **"Vị trí chính xác"** (Precise Location), **"Không bao giờ"** (Never), **"Hỏi vào lần sau"** (Ask Next Time), **"Trong lúc dùng ứng dụng"** (While Using the App), **"Xoá Lịch sử và Dữ liệu Trang web"** (Clear History and Website Data).

---

## Sources

- Google, "Manage your location settings in Chrome" — Android: https://support.google.com/chrome/answer/142065?hl=en&co=GENIE.Platform%3DAndroid (Vietnamese: same URL with `hl=vi`)
- Google, "Manage your location settings in Chrome" — iPhone & iPad: https://support.google.com/chrome/answer/142065?hl=en&co=GENIE.Platform%3DiOS
- Google, "Change site settings permissions" — Android: https://support.google.com/chrome/answer/114662?hl=en&co=GENIE.Platform%3DAndroid (View site information → Permissions → Reset permissions)
- Google, "Change site settings permissions" — iPhone & iPad (Content Settings): https://support.google.com/chrome/answer/114662?hl=en&co=GENIE.Platform%3DiOS
- Apple, "Turn Location Services and GPS on or off on your iPhone" (updated Jan 2026): https://support.apple.com/en-us/102647
- Apple, "About privacy and Location Services in iOS, iPadOS and watchOS": https://support.apple.com/en-us/102515 (LS-off behavior; Reset Location & Privacy path)
- Apple, "Delete your Safari history, cache, and cookies on iPhone": https://support.apple.com/en-us/105082 (confirms Settings → Apps → Safari organization)
- Apple iPhone User Guide, "Customize your Safari settings on iPhone": https://support.apple.com/guide/iphone/customize-your-safari-settings-iphb3100d149/ios
- Drexel LeBow KB, "How to allow location permission on an iPhone" (detailed aA → Website Settings flow; Safari Websites listing): https://www.lebow.drexel.edu/about/support-services/knowledge-base/how-allow-location-permission-iphone
- Google location device toggle: https://support.google.com/accounts/answer/3467281
- Chrome Community thread (Jan 2026), system-level Chrome location required: https://support.google.com/chrome/thread/405201367/location-problem-in-some-site
- flutterlocation issue #878 (Chrome iOS Block recovery via Content Settings): https://github.com/Lyokone/flutterlocation/issues/878
- MDN GeolocationPositionError / watchPosition (error codes): https://developer.mozilla.org/en-US/docs/Web/API/GeolocationPositionError
- Stack Overflow, iOS Safari geolocation with Location Services off (PERMISSION_DENIED): https://stackoverflow.com/questions/65379949/geolocation-getcurrentposition-on-safari-on-ios

## Unresolved questions

1. iOS 26 Safari: the AA page-menu item is assumed to remain "Website Settings" post-Liquid-Glass redesign; sources consulted describe iOS 15–18 verbatim. Low risk, but worth a 30-second device check before quoting VN wording verbatim in prod.
2. Chrome iOS "Content Settings" placement inside Chrome's own Settings varies by Chrome version; the iOS-tab support page confirms it exists but current exact nesting may differ.
3. Apple VN labels are the standard Vietnamese iOS localization from knowledge, not fetched from Apple's VN site verbatim.
