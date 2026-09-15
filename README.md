# TikTok AI Access API

FastAPI gateway for TikTok Login Kit/OAuth 2.0, Display API, Content Posting API and Data Portability API. No TikTok password is ever requested.

## Required Railway variables
- `TIKTOK_CLIENT_KEY`
- `TIKTOK_CLIENT_SECRET`
- `TIKTOK_REDIRECT_URI`
- `DATABASE_URL`
- `BASE_URL`

Optional `API_KEY`: when set, `/api/*` requires `X-API-Key`; when empty, the API is URL-only for simple AI HTTP clients.

For SQLite, mount a Railway volume at `/data` and use `sqlite:////data/tiktok.db`. Postgres is also supported with a SQLAlchemy PostgreSQL URL.

Register exactly `${BASE_URL}/auth/tiktok/callback` in the TikTok developer portal.

## Discovery
`/api`, `/api/capabilities`, `/api/docs`, `/openapi.json`, `/api/health`.

## Real account endpoints
`/api/me`, `/api/profile`, `/api/stats`, `/api/videos`, `/api/videos/{id}`, `/api/creator`, `/api/post/status/{publish_id}`, `/api/video/upload`, `/api/video/publish`.

## Data Portability bridge
`/api/data/request`, `/api/data`, `/api/data/status`, `/api/data/cancel`, `/api/data/download`, `/api/export`, `/api/export/{request_id}`.

TikTok prepares the export archive asynchronously. The service exposes the official request/status/download flow instead of inventing live endpoints for private account data that TikTok does not expose as normal APIs.

## Capability boundaries
Display API covers profile and public videos. Content Posting covers direct posting and draft upload with approved scopes. Data Portability covers full, posts/profile, activity, and direct-message exports with single or ongoing permissions. Research Tools are separate, approval-gated research access to public TikTok data and are not used as private-account access.
