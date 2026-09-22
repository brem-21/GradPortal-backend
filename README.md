# GradPortal

A portal for graduate openings, scholarships, assistantships and research posts in
**Computer Science, Artificial Intelligence, Data Science, Data Engineering and Data
Analytics** — each carrying the person to email about it, reachable from the applicant's
own mailbox — plus an admissions-committee review of their application documents and a
voice-or-text assistant grounded in those documents.

## Services

| Service | Port | Owns | Schema |
| --- | --- | --- | --- |
| **core-api** | 8000 | Auth, profiles, opportunities, ingestion agent, mentorship, outreach, notifications | `public` |
| **doc-service** | 8001 | Uploads, parsing, chunking, embeddings, vector retrieval | `docs` |
| **rag-service** | 8002 | Agentic RAG chat over the user's own documents | `rag` |
| **eval-service** | 8003 | Admissions-committee document review | `evaluation` |
| **voice-service** | 8004 | ElevenLabs speech-to-text and text-to-speech | none (stateless) |
| **frontend** | 3000 | Next.js 15 App Router, Aker design system | — |

Each service owns one Postgres schema and never reads another's tables. They share a
physical database only because running four locally is not worth the operational cost;
the schema boundary is what keeps them independently migratable.

- **Backend** — FastAPI + SQLAlchemy 2 + PostgreSQL (pgvector), arq worker for scheduled
  crawls, reminders and digests.
- **Frontend** — Next.js 15 (App Router) + Tailwind v4, built on the **Aker** design
  system (see `frontend/DESIGN.md`).
- **Auth** — Auth.js v5 owns Google and LinkedIn OIDC and mints one HS256 token that
  every service verifies. No service holds a provider secret.

---

## Running everything

```bash
./run-all.sh        # infrastructure + all five services + worker + frontend
./health-check.sh   # what is up, and what is missing a key
./smoke-test.sh     # signs in and exercises every page and endpoint
```

## Validating without OAuth

Google and LinkedIn need registered apps. Until then, a password-less
development sign-in lets the whole app be exercised:

```bash
cd backend && python -m scripts.bootstrap demo-users   # admin / mentor / student
# frontend/.env.local
ALLOW_DEV_SIGNIN=true
```

`/signin` then offers three accounts, or any email you type:

| Account | Role | Useful for |
| --- | --- | --- |
| `admin@gradportal.example.com` | admin | Ingestion sources, site media, success stories, publishing opportunities |
| `mentor@gradportal.example.com` | mentor | Mentor directory, mentorship requests, submitting opportunities |
| `student@gradportal.example.com` | student | The first-run flow — this one is deliberately not onboarded |

Two independent gates gate it: the flag **and** a non-production build. Leaving
`ALLOW_DEV_SIGNIN=true` in a production build still will not enable it.
A provider button only renders once its client ID and secret are present, so the
sign-in page never shows an option that dead-ends.

`./smoke-test.sh` drives this end to end — health, public endpoints, auth
enforcement, sign-in, every authenticated page, the admin pages and the service
APIs. It exits non-zero on failure, so it works in CI.

> Demo accounts use `example.com`, which RFC 2606 reserves. Reserved *TLDs* like
> `.test` and `.local` look like the obvious choice but `email-validator`
> rejects them as special-use, so an account on one cannot authenticate.

---

## Quick start

```bash
# 1. Infrastructure (Postgres :5437, Redis :6379, Mailpit :8025)
docker compose up -d

# 2. Backend
cd backend
uv venv --python 3.12
uv pip install -e ".[dev]"
cp .env.example .env
python -m scripts.bootstrap keygen        # paste the two secrets into .env
alembic upgrade head
python -m scripts.bootstrap seed-sources
python -m scripts.bootstrap demo-data     # optional sample opportunities
python -m scripts.bootstrap make-admin you@example.com
uvicorn app.main:app --reload             # http://localhost:8000/docs

# 3. Worker (separate shell) — scheduled crawls, reminders, digests
cd backend && arq app.workers.main.WorkerSettings

# 4. AI services
cd services
uv venv --python 3.12
uv pip install -e ".[dev]"
cp .env.example .env                      # AUTH_JWT_SECRET must match backend/.env
alembic -c alembic-doc.ini  upgrade head
alembic -c alembic-rag.ini  upgrade head
alembic -c alembic-eval.ini upgrade head
uvicorn doc_service.main:app   --reload --port 8001
uvicorn rag_service.main:app   --reload --port 8002
uvicorn eval_service.main:app  --reload --port 8003
uvicorn voice_service.main:app --reload --port 8004

# 5. Frontend
cd frontend
npm install
cp .env.example .env.local                # AUTH_SECRET must equal backend AUTH_JWT_SECRET
npm run dev                               # http://localhost:3000
```

> Do not run `npm run build` while `npm run dev` is running — they share `.next`
> and the build will break the dev server until you restart it.

Postgres is on **5437**, not 5432, to avoid colliding with other local projects.

### The two secrets

`python -m scripts.bootstrap keygen` prints both:

| Secret | Where | Purpose |
| --- | --- | --- |
| `AUTH_JWT_SECRET` | `backend/.env` **and** `frontend/.env.local` as `AUTH_SECRET` | Must be byte-identical. Auth.js signs, FastAPI verifies. |
| `TOKEN_ENCRYPTION_KEY` | `backend/.env` | Fernet key encrypting stored OAuth refresh tokens. Rotating it forces every user to reconnect their mailbox. |

### API keys

| Key | Needed by | What breaks without it |
| --- | --- | --- |
| `OPENROUTER_API_KEY` | doc, rag, eval | Everything AI: indexing, Counsel and the Committee. **One key covers all three** — embeddings included. |
| `ELEVENLABS_API_KEY` | voice-service | No speech input, no spoken replies. Text still works. |
| `INTERNAL_SERVICE_TOKEN` | all services | `/internal/*` routes refuse every caller. |
| `OPENAI_API_KEY` | doc-service | Optional. Set it only to bill embeddings to OpenAI directly instead of through OpenRouter. |

**Embeddings go through OpenRouter.** Its `POST /api/v1/embeddings` endpoint is
OpenAI-compatible and serves `openai/text-embedding-3-small` at 1536 dimensions,
honouring the `dimensions` parameter and batching. No embedding model appears in
OpenRouter's `/models` catalogue, which makes the endpoint easy to miss — it
works regardless.

Every service reports which of its keys are missing at `/health`, and each screen that
depends on one says so in place rather than failing opaquely.

**Models.** OpenRouter is pointed at OpenAI models by default —
`openai/gpt-4o-mini` for chat, `openai/o4-mini` for the reasoning toggle and all
document evaluation, `openai/text-embedding-3-small` for indexing. Change
`OPENROUTER_DEFAULT_MODEL`, `OPENROUTER_REASONING_MODEL` or `EMBEDDING_MODEL` in
`services/.env` to use anything else OpenRouter serves.

**Web search** uses OpenRouter's `web` plugin, opt-in per message. It costs
roughly 3500x a plain call (~$0.007 vs ~$0.000002), which is why it is a toggle
and never implicit.

### OAuth setup

Run the checker first — it verifies what it can without a browser and prints
the exact redirect URIs to register:

```bash
cd frontend && npm run check:oauth
```

**Google** — https://console.cloud.google.com

1. APIs & Services → Credentials → Create credentials → **OAuth client ID** →
   *Web application*.
2. Authorised redirect URI: `http://localhost:3000/api/auth/callback/google`
   (add the production URL too when you deploy).
3. APIs & Services → Library → enable the **Gmail API**. Without this the
   token exchange succeeds and every send fails.
4. OAuth consent screen → Scopes → add
   `https://www.googleapis.com/auth/gmail.send`.
5. While the consent screen is in *Testing*, add each account you will sign in
   with under **Test users** — otherwise Google refuses with `access_denied`.
6. Put the client ID and secret in `frontend/.env.local` as `AUTH_GOOGLE_ID`
   and `AUTH_GOOGLE_SECRET`.

**LinkedIn** — https://developer.linkedin.com

1. Create an app and verify it against a LinkedIn Page you administer.
2. Products → request **Sign In with LinkedIn using OpenID Connect**. Nothing
   works until it is granted; it is usually immediate.
3. Auth → Authorized redirect URLs:
   `http://localhost:3000/api/auth/callback/linkedin`
4. Put the client ID and secret in `frontend/.env.local` as
   `AUTH_LINKEDIN_ID` and `AUTH_LINKEDIN_SECRET`.

A provider button only renders once both its variables are present, so the
sign-in page never offers an option that dead-ends. Restart the dev server
after editing `.env.local` — Next reads it at boot.

### What each provider can do

|  | Google | LinkedIn |
| --- | --- | --- |
| Sign in | yes | yes |
| Email address | yes | yes |
| Name and picture | yes | yes |
| Locale | yes | yes |
| Headline, positions, education | no | no — needs the partner-gated `r_basicprofile` |
| **Send email as the user** | **yes**, via `gmail.send` | **no** — LinkedIn has no send API at all |

**LinkedIn cannot send mail.** It is an identity provider here and nothing
more. A member who signs in with LinkedIn and wants outreach to leave their
own address authorises Google separately from Settings → Connected accounts.
That second authorisation must use the same email address, because accounts
are keyed by email.

### Verifying a real sign-in

Signing in successfully and being able to send are different things: Google
only returns a refresh token on an explicit offline consent. **Settings →
Connected accounts** shows, per provider, whether a refresh token was stored,
which scopes were granted, and the specific reason sending is blocked when it
is. `GET /api/v1/auth/connections` returns the same thing as JSON.

---

## How email to contacts works

Enquiries are sent **from the user's own mailbox**, not from a platform domain:

1. At sign-in, Google returns a refresh token alongside the `gmail.send` grant.
2. Auth.js posts it to `POST /auth/session/sync`; the API stores it Fernet-encrypted.
3. `POST /outreach/draft` composes a prefilled enquiry from the user's profile and the
   opportunity's contact.
4. The user edits it and presses send. `POST /outreach/send` exchanges the refresh token
   for an access token and calls the Gmail API.

The message lands in the user's Sent folder, is DKIM-signed by their domain, and replies
come straight back to them. Microsoft Graph works the same way via `Mail.Send`.

Guardrails: 25 sends per user per day, and the same contact at most once per 24 hours
per opportunity. Nothing is ever sent without the user pressing send.

---

## The ingestion agent

An adapter turns one configured `Source` row into `RawOpportunity` records. Everything
downstream — classification, deadline parsing, dedupe, contact extraction, persistence,
notification fan-out — is shared in `app/agent/pipeline.py`, so every source is treated
identically. **Adding a source is a database row, not a code change.**

| Adapter | Status | Notes |
| --- | --- | --- |
| `rss_feed` | Working | RSS/Atom. Optionally fetches each detail page for contacts. |
| `html_listing` | Working | CSS-selector scraping of a listing page, with pagination. |
| `json_api` | Working | Declarative field mapping for official APIs and job boards. |
| `linkedin` | **Credential-gated** | No public jobs API exists, and scraping breaches LinkedIn's User Agreement. Transformation logic is complete; set `LINKEDIN_PARTNER_ACCESS_TOKEN` once you hold a Talent Solutions partner agreement. |
| `handshake` | **Credential-gated** | Postings sit behind institutional SSO. Set `HANDSHAKE_API_TOKEN` and `HANDSHAKE_INSTITUTION_ID` once your school issues them. |

Gated adapters report a clear `skip_reason` rather than silently failing or falling back
to scraping.

### Scope filter

Only the five fields are ingested. A posting whose title and description match none of
them is counted as `skipped_out_of_scope` and never stored. In a live run against
Opportunity Desk, 10 items fetched yielded 1 stored and 9 filtered — that ratio is the
filter working, not a bug.

### Contact extraction

`app/agent/contacts.py` mines `mailto:` links and body text, scores each address by
provenance, and records a confidence the UI shows the user:

| Confidence | Meaning |
| --- | --- |
| 1.0 / verified | Human-entered, or an email to it delivered successfully |
| ≥ 0.85 | A named role on the source page (admissions officer, PI, coordinator) |
| ≥ 0.70 | `first.last@` — almost certainly an individual |
| ≥ 0.55 | Departmental mailbox, not a person |

`webmaster@`, `noreply@`, analytics addresses and image filenames are blocklisted.

### Verifying a source before enabling it

HTML-listing sources ship **disabled**, because site markup changes constantly and a
stale selector fails silently. Confirm one first:

```bash
python -m app.agent.probe --url https://university.edu/phd --selector "article.card"
python -m app.agent.probe --url https://university.edu/phd/123 --contacts
```

The probe prints what each selector matched and what the classifiers made of it. The
seed catalogue in `app/agent/seeds.py` annotates every entry as VERIFIED, BLOCKED (the
host returns 403 to non-browser clients) or UNVERIFIED.

### Schedule (arq, UTC)

| Time | Job |
| --- | --- |
| 02:00 | Crawl every enabled source |
| 03:30 | Expire past-deadline postings |
| 06:00 | Deadline reminders for saved opportunities |
| 07:00 | Daily digest |
| Mon 07:30 | Weekly digest |

---

## Documents, evaluation and the assistant

### Upload and indexing (doc-service)

PDF, DOCX, TXT and MD. A scanned PDF with no selectable text is rejected with a
message saying to run OCR, rather than silently indexing nothing.

Each document is parsed, split on paragraph boundaries into ~800-token chunks with
a 120-token overlap, embedded with `text-embedding-3-small` (1536-dim) and stored in
pgvector with an HNSW cosine index. Chunks carry the page number and the detected
section heading, so a citation can say "CV, Experience, page 1" rather than "chunk 7".

Every retrieval filters on `user_key` before ranking. A user cannot reach another
user's chunks, and the internal search route additionally requires the service token.

### Admissions review (eval-service)

Documents are read against a rubric chosen by **document kind × track**. The two
tracks are genuinely different readings, not a relabelling:

| | Master's | PhD |
| --- | --- | --- |
| CV, top criterion | Technical depth and coursework (0.28) | Research output and trajectory (0.34) |
| SOP criteria | Goal clarity, programme fit, evidence of preparation | Research question maturity, literature positioning, supervisor fit |
| The question being asked | "Will this person cope with our coursework and be employable?" | "Can this person produce original research, and does someone here want to supervise it?" |

Fourteen rubrics ship (CV, SOP, motivation letter, recommendation, transcript,
research proposal and a generic fallback, each × two tracks). Every rubric's weights
sum to 1.0, which is asserted in the test suite.

A run reviews each document concurrently, then does a second **committee synthesis**
pass over all of them together — that is where contradictions between documents,
duplicated recommendation content and missing documents get caught, which no
single-document review can see. Output is a 0-100 score per document, a weighted
overall, a verdict, priority actions, and per-criterion findings graded
strength / minor / major / critical with a verbatim quote and one concrete fix.

Reviews always use the reasoning model. `GET /evaluations/rubrics` exposes the
criteria so an applicant can see what is being judged before spending a run.

### Assistant (rag-service + voice-service)

Agentic, not a single embed-and-answer: the assistant plans its own search queries
from the conversation (resolving "does it mention that?" into a standalone query),
retrieves, judges whether what came back is sufficient, and searches again with
different phrasing if it is not. It stops at two rounds — beyond that it mostly
re-finds the same chunks.

Answers are grounded hard. Every claim carries a `[n]` citation, and when the
documents do not cover the question it says so and names what is missing rather than
answering from general knowledge. The UI shows the queries it ran and the excerpts it
used, so retrieval is inspectable.

Voice is both directions: ElevenLabs Scribe for speech-to-text, and TTS for spoken
replies. Answers destined for speech are shaped for the ear and stripped of markdown
and citation markers before synthesis, while the transcript keeps them.

---

## Site content (admin-managed)

Background media and success stories are content, not code. An admin changes
them at `/admin/media` and `/admin/stories` without a deploy.

### Media

Upload JPEG, PNG, WebP, AVIF, **GIF** or silent MP4/WebM, and assign each file
to one or more **slots** — hero, closing band, mentor card, footer, sign-in,
the overview community band, and the photo gallery. A slot rotates through
everything assigned to it, so uploading one more file lengthens that slideshow
rather than replacing anything.

Alt text is required, identical uploads are de-duplicated by content hash (slots
merge instead of creating a second copy), and files are served from core-api at
`/media/<name>`.

> A silent MP4 gives the same effect as a GIF at a fraction of the size, with
> hardware decode and no 256-colour banding. GIF is accepted, but prefer MP4.

The public page reads `GET /api/v1/site/media` — unauthenticated, because the
landing page shows these to signed-out visitors — and falls back to the
photographs bundled in `frontend/public/media` when a slot is empty or core-api
is unreachable, so a fresh install never renders black bands.

`python -m scripts.bootstrap seed-media` imports those bundled photographs into
the admin store on first setup.

### Success stories

Name, outcome, quote, optional photograph, ordering, publish state.

**A story cannot be published until consent is recorded against it**, enforced
in the API and not only the UI. Unpublished and unconsented stories are never
returned by the public endpoint, and the carousel is hidden entirely when there
are none — an empty section is better than a fabricated testimonial. Stories
without a photograph render as monogram initials.

This is not decoration: inventing testimonials and presenting them as genuine is
deceptive advertising (FTC endorsement guides in the US, CAP/ASA rules in the
UK), and pairing an invented quote with a stock photograph of a real person uses
their likeness to endorse something they have never heard of.

---

## Notifications

Every event writes an in-app row **and**, subject to the user's preference, an email.
Users choose instant / daily / weekly / off. Deadline reminders always email regardless
of digest setting — they are time-critical — and each (opportunity, reminder-window)
pair fires exactly once.

Events: new match, deadline reminder, opportunity submitted, opportunity approved,
mentorship request, mentorship accepted/declined, outreach sent, outreach failed.

In development, Mailpit catches everything at **http://localhost:8025**.

---

## Roles

| Role | Can |
| --- | --- |
| `student` | Browse, filter, save, track applications, email contacts, request mentorship |
| `mentor` | All of the above, plus appear in the directory, accept mentees, and post opportunities (queued for review) |
| `admin` | All of the above, plus publish immediately, approve the review queue, and manage ingestion sources |

Ticking "list me as a mentor" in onboarding or on the profile promotes a student to
mentor. Admin is granted with `python -m scripts.bootstrap make-admin <email>`.

---

## Layout

```
backend/
  app/
    agent/        ingestion: adapters/, pipeline, normalize, contacts, probe, seeds
    api/v1/       auth, users, opportunities, outreach, notifications, mentorship, sources
    core/         config, db, security (JWT verify), crypto (Fernet), enums
    models/       user, opportunity, engagement
    schemas/      pydantic request/response
    services/     mailer (SMTP), providers (Gmail/Graph), notifications, matching
    workers/      arq tasks and schedule
  scripts/        bootstrap CLI
  tests/          normalize, contacts, providers
frontend/
  DESIGN.md       the Aker design system — read before touching the UI
  src/
    app/          landing, signin, (portal)/*
    components/   Aker primitives, nav pill, forms, opportunity card
    lib/          server API client, server actions, formatting, options
```

---

## Testing

```bash
cd backend && .venv/bin/pytest tests/ -q     # 33 tests
cd backend && .venv/bin/ruff check app/
cd frontend && npx tsc --noEmit && npm run build
```

`python -m scripts.bootstrap token you@example.com` mints a development API token for
curl and Swagger, so the API can be exercised without the frontend. It refuses to run
outside `ENVIRONMENT=development`.

---

## Known limits

- **Text-to-speech needs a paid ElevenLabs plan.** Free accounts cannot use library
  voices through the API (`paid_plan_required`). Speech-to-text works on free. The
  service surfaces the real provider message rather than a generic failure.
- **LinkedIn sign-in only enriches name, picture and locale.** Both Google and
  LinkedIn implement plain OpenID Connect, which carries exactly that. Headline,
  positions and education require LinkedIn's `r_basicprofile` product, which is
  partner-gated — so those fields stay user-entered.
- **There are no success stories out of the box**, by design. Add real ones at
  `/admin/stories` with consent recorded. The carousel stays hidden until then.
- **Bundled media is Pexels campus photography**, re-graded locally to the Aker
  palette — not photography of your institution. Replace it at `/admin/media`, or
  with `npm run fetch:media` and an Unsplash key. iStock and Google image-search
  thumbnails were deliberately not used: the first is paid stock, the second is a
  cache of someone else's image with unknown rights. See `public/media/CREDITS.md`.
- **Uploaded media is stored on local disk** under `backend/.media` and served by
  core-api. Fine for one host; production wants an object store and a CDN. The
  seam is `app/services/media_storage.py`.
- **Dev sign-in must be off in production.** It is double-gated, but
  `ALLOW_DEV_SIGNIN` should still be absent from any deployed environment.
- **Profile pictures are required** to finish onboarding but are stored as a URL, not
  an upload; there is no avatar object storage wired up.
- **Retrieval thresholds are measured, not guessed.** `rag_service/config.py`
  records the cosine distances observed against real documents and explains why
  the answer is not gated on them: for a short document, relevant and irrelevant
  queries overlap heavily, so only the model reading the text can judge.
- **LinkedIn and Handshake are off by default** and cannot be switched on without the
  credentials described above. This is a legal and technical constraint, not an
  unfinished feature.
- **Several seeded feeds are 403-blocked** by Cloudflare (FindAPhD, Nature Careers,
  EURAXESS, academicpositions). They ship disabled and annotated. Getting them needs a
  published feed URL or a partnership, not a spoofed user agent.
- **Classification is rule-based**, not model-based, because the field set is small and
  closed and rules are debuggable when a site changes wording. It will occasionally
  mislabel an unusual posting.
- **CV upload is a URL field**, not a file upload — no object storage is wired up yet.
- **No realtime push.** In-app notifications refresh on navigation; email covers urgency.
