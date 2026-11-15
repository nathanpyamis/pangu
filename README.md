# Pangu Pati Platform

Party website, member register, candidate selection, ID cards, offline field-agent app and
an executive dashboard for the 2027 National General Election. Built from the pngparty project
as a separate project. pngparty itself is unchanged.

Runs **local-first**: SQLite, DEBUG on, no `.env`, nothing to install beyond pip.
Production (Render) is switched on by environment variables, with no code changes.

## Run locally (Windows cmd)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python manage.py makemigrations geo accounts members cms candidates
python manage.py migrate
python manage.py seed_provinces
python manage.py seed_party
python manage.py createsuperuser
python manage.py runserver
```

A superuser is treated as **National Executive** everywhere.

## Where things are

| URL | Who | What |
|---|---|---|
| `/` | Public | Kitzu-style one-pager: leaders header, About, Policies, Candidates, News, Join, Contact |
| `/candidates/apply/` | Public | Intending-candidate application (8 sections, photo + document uploads) |
| `/candidates/status/` | Applicants | Track an application with reference + phone |
| `/portal/login/` | Staff | One login. Field agents are sent on to `/agent/` |
| `/portal/` | Executives, coordinators | **Overall progress** dashboard |
| `/portal/candidates/` | Executives, coordinators | **Candidate database**: review, score, decide, letters, cards, CSV |
| `/portal/members/` | Executives, coordinators | **Members database**: filter, verify, print cards, CSV |
| `/portal/staff/` | Executives, coordinators | **Field officers**: staff ID cards, sync activity |
| `/agent/` | Field agents | Offline registration app (unchanged from pngparty, Pangu theme) |
| `/verify/<uuid>/` | Public | Member card QR check |
| `/verify/candidate/<uuid>/` | Public | Candidate card QR check |
| `/verify/staff/<uuid>/` | Public | Officer card QR check |
| `/admin/` | Staff with admin rights | Party profile, leaders, policies, news, users, everything else |

Coordinators see only their own province in every portal screen; executives see everything.

## Roles

| Role | Portal | Can do |
|---|---|---|
| National Executive (`EXEC`, or any superuser) | Everything, nationwide | Endorse or reject candidates, letters, all cards, CSV exports |
| Provincial Coordinator (`COORDINATOR`) | Own province | Score candidates, verify members, print member, candidate and agent cards |
| Field Agent (`AGENT`) | None: uses `/agent/` | Register members offline |

## Who can register members

There is no sign-up page. Field officer accounts are created only by an administrator in
**Admin → Users** (role Field Agent with an electorate, or Provincial Coordinator with a province).
Every agent-app login, token refresh and sync is checked, so access stops at once when an admin:

- unticks **Active** on the user, or
- suspends the officer's ID card or its **Valid until** date passes (Portal → Field officers), or
- removes the assigned electorate or province.

The officer sees "Your access to member registration has been stopped". Records already on the
phone are kept and sync once access is restored.

On a shared phone, nothing in the agent app (form, queue, history) shows without a login.
Each officer sees and sends only their own registrations; logging out hides them, and the next
officer only sees a count of unsent records left by someone else. Logins are limited to 10 attempts a minute per
username. The public **Join** panel on the home page is separate: anyone can apply online there,
and those applications wait as *Pending* until a coordinator verifies them.

## Residential address and map point

Every registration (agent app and the public Join form) records a **residential address** in
words (section & lot, street or landmark, suburb or village) and, optionally, a **map point**:

- **Use GPS here**: the phone's GPS, which works with no data signal. Take it at the member's home.
- **Tap the map** to place or move the point. The map pictures come from OpenStreetMap and need
  signal; offline the map says so and a GPS point is still saved.

Points outside PNG are refused. Staff see the address and an **Open map** link in Portal →
Members, in Admin and in the CSV export (latitude, longitude, GPS or map).

Phones only share GPS with sites served over **HTTPS** (Render provides it), or with
`localhost` on the PC itself. Testing the agent app on a phone at `http://192.168.x.x:8000`
will not get a GPS fix; tapping the map still works there.

## ID cards (CR80, or A4 sheets of 10 or 8)

| Card | Number | Issued when | QR page says |
|---|---|---|---|
| Member | `PANGU-MOR-A1B2C3` | Member verified | Valid party member |
| Candidate | `PANGU-CAN-MOR-4F7K` | Candidate endorsed | Endorsed party candidate, seat |
| Field officer | `PANGU-STF-MOR-9Q2D` | First card print or save in Portal → Field officers | Authorised party officer, role, area |

All three share one drawing module (`apps/idcards/cardpdf.py`, ReportLab, Pangu gradient + logo).
Suspending an officer's card, setting an expiry date or disabling their login turns their QR
check to **not valid** at once. The prefix comes from `PARTY_CODE` in settings.

## Candidate workflow

Submitted → Under review (automatic on first score) → Shortlisted → Interview → **Endorsed** /
Not endorsed. Withdrawn is possible at any stage; a rejection can be reopened.
One endorsed candidate per electorate (a second endorsement is blocked). Duplicates (same NID,
or same name + phone) are flagged, never deleted. Every change is in the audit trail.
Candidate documents are stored in `PRIVATE_MEDIA_ROOT`, outside `/media/`, and only open
through the logged-in portal.

## Edit the content

Admin → Cms → **Party profile**: name, tagline, rotating lines, intro, about text, leaders
header image and caption, logo, election date (turns on the countdown and the candidate age
check), application window, endorsement-letter signatory, contacts and socials.
**Leaders**, **Policy documents** and **News posts** have their own sections.
Everything marked `[Placeholder]` needs real text.

`seed_party` only adds Morobe's open electorates. Load the official PNGEC open electorates for
every province (Admin → Geo → Electorates, or a fixture) before candidate applications open.

## Production on Render (later)

`pip install -r requirements-prod.txt` and set `POSTGRES_HOST` (+ the other `POSTGRES_*` vars),
`DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `PUBLIC_BASE_URL` (printed into every QR code) and
`PRIVATE_MEDIA_ROOT` (a persistent disk). Setting `POSTGRES_HOST` turns DEBUG off and enables
WhiteNoise; run `python manage.py collectstatic`. See `.env.example`.

## Structure

```
pangu/
├── config/               settings.py (local vs production, PARTY_CODE) · urls.py
├── templates/admin/      admin theme (Pangu green to gold)
├── apps/
│   ├── cms/              PartyProfile, Leader, NewsPost, PolicyDocument, ContactMessage, home page
│   ├── geo/              Province, Electorate, seed_provinces
│   ├── accounts/         User (role, province, electorate) + StaffProfile (officer card)
│   ├── members/          Member, SyncLog, sync API, duplicate checks, member cards
│   ├── candidates/       CandidateApplication, reviews, audit trail, endorsement letter
│   ├── idcards/          shared card drawing, QR check pages, field-officer screens
│   ├── portal/           staff login, overall progress dashboard, members database
│   └── pwa/              /agent/ offline app shell, service worker, manifest
└── static/
    ├── site/             css · js · img (pangu-logo.png, leaders-header.jpg)
    ├── portal/           css
    └── pwa/              js (IndexedDB, sync, app) · icons
```

The sync contract and API endpoints are the same as pngparty's
(`POST /api/members/sync/`, `GET /api/geo/electorates/`, `POST /api/auth/token/` …).
