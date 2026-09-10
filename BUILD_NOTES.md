# BUILD_NOTES

## Assumptions

1. **GMGN primary path = CLI subprocess** (`npx --yes gmgn-cli ... --raw` or global `gmgn-cli`). HTTP mode is a secondary path hitting the same OpenAPI routes documented in GMGNAI/gmgn-skills (`POST /v1/trenches`, `GET /v1/token/info`, `GET /v1/user/created_tokens`). Auth via `GMGN_API_KEY` env (also injected into CLI child process).
2. **Chain id** is the GMGN string `robinhood` (configurable via `SCAN_CHAINS` CSV for future chains).
3. **ATH USD** is parsed from string/number fields `dev.ath_token_info.ath_mc` and `portfolio created-tokens` → `token_ath_mc` / `creator_ath_info.ath_mc`.
4. **Twitter** uses X API v2 recent search with Bearer Token. OAuth1-only credentials log a warning and skip (interface remains swappable via `TwitterProvider`).
5. Follower rule is **strictly greater than** `FOLLOWER_THRESHOLD` (default 10000).
6. High-ATH alert requires **prior** launches (excludes the current new token address). Current-token-only ATH does not trigger.
7. On startup, existing trenches results are marked seen (bootstrap) so only subsequently appearing tokens alert.
8. Missing Telegram/Twitter/GMGN keys: process still starts, logs warnings, skips the corresponding features. Without Telegram token, no polling; alerts are logged as preview.
9. Full-chain history queries `robinhood,sol,bsc,base,eth` sequentially with short delays for rate limits.
10. Blacklist is cumulative across reasons; twitter authors and dev addresses are separate entity namespaces.

## File layout

```
rh-telegram-bot/
  pyproject.toml
  requirements.txt
  .env.example
  Dockerfile
  docker-compose.yml
  README.md          # Chinese
  BUILD_NOTES.md
  data/              # sqlite runtime (volume)
  src/
    __main__.py
    main.py
    health.py
    logging_setup.py
    config/settings.py
    storage/db.py
    gmgn/{client,models}.py
    twitter/{base,x_api}.py
    blacklist/service.py
    alerts/{formatter,sender}.py
    scanner/pipeline.py
    bot/{app,handlers}.py
  tests/
    test_blacklist.py
    test_ath.py
    test_follower_filter.py
```

## Verification

- `pip install -e ".[dev]"`
- `pytest`
- `python -m src` (with `.env`)
