# iOS MVP — Before You Start

## 1. Add iOS redirect URI in Authentik

The iOS PKCE flow needs `secondbrain://auth/callback` registered as an allowed redirect URI.

1. Go to `https://auth.smoothstudy.ai` → Admin Interface
2. Applications → Applications → open the **second-brain** application → Edit
3. In **Redirect URIs/Origins**, add: `secondbrain://auth/callback`
4. Save

## 2. Find your machine's LAN IP

The iOS simulator cannot reach `localhost` — it needs the host machine's LAN IP.

```bash
ipconfig getifaddr en0
```

Note the result (e.g. `192.168.1.42`). You'll use it as `BACKEND_URL` in `Config-Debug.xcconfig`.

## 3. Install Tuist (if not already installed)

```bash
brew install tuist
```

## 4. Fill in xcconfig values

When Task 2 of the plan asks you to fill in `Config-Debug.xcconfig`, use these values:

```
BACKEND_URL = http://<YOUR_LAN_IP>:8000
AUTHENTIK_AUTHORIZE_URL = https://auth.smoothstudy.ai/application/o/second-brain/authorize/
AUTHENTIK_TOKEN_URL = https://auth.smoothstudy.ai/application/o/token/
AUTHENTIK_CLIENT_ID = second-brain
AUTHENTIK_REDIRECT_URI = secondbrain://auth/callback
```

`Config-Release.xcconfig` is the same except `BACKEND_URL = https://smoothstudy.ai` (or wherever the prod API lives).

## Done?

Once steps 1–3 are done you can start the plan at:
`.agents/superpowers/plans/2026-05-09-ios-mvp.md`
