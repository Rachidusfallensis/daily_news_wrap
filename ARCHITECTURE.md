# بَصِيرَة — Baṣīra · Architecture & Stack Technique

> Document de référence : stack, technos, outils, architecture, et **qui fait quoi**.
> Public : développeur·euse rejoignant le projet ou voulant comprendre le système de bout en bout.

---

## 1. Vue d'ensemble

**Baṣīra** (بَصِيرَة — *« perspicacité, discernement »* en arabe) est un **lecteur RSS auto-hébergé orienté recherche doctorale**. Chaque article est **scoré, étiqueté et résumé par un LLM avant** que tu ne l'ouvres. Les papiers de recherche sont enrichis avec les métadonnées Semantic Scholar et séparés des billets de blog au niveau de la donnée.

Le système couvre deux usages :
1. **Veille littéraire** continue (papiers arXiv / ACL / OpenReview, état de l'art externe).
2. **Lecture quotidienne** infra / IA / SE de haute densité.

**Principe directeur :** tout tourne sur ta propre machine. Rien ne sort de l'hôte, sauf si tu configures explicitement OpenRouter ou un serveur GPU universitaire.

---

## 2. Stack technique (résumé)

| Couche | Technologies |
|--------|-------------|
| **Frontend** | React 18 · TypeScript · Vite 5 · Tailwind CSS · Zustand · PWA (vite-plugin-pwa) · react-virtuoso · lucide-react · date-fns |
| **API** | Python 3.12 · FastAPI · SQLAlchemy · SQLite (mode WAL) · Pydantic · structlog |
| **Extraction** | trafilatura · readability-lxml · BeautifulSoup · httpx (async) |
| **Embeddings** | nomic-embed-text via Ollama · ChromaDB (in-process, persistant) |
| **Scoring LLM** | Routage 3 niveaux : GPU université (OpenAI-compatible) → Ollama local → OpenRouter |
| **Recherche littérature** | Semantic Scholar API · OpenAlex API · clustering (AgglomerativeClustering / HDBSCAN) |
| **Orchestration** | Docker Compose · Caddy (reverse proxy + TLS auto) · APScheduler · tenacity |
| **Déploiement front (option cloud)** | Cloudflare Pages + Pages Functions (proxy `/api/*`) · GitHub Actions |

---

## 3. Architecture des services

Le système est un ensemble de **6 services Docker** sur un **réseau interne unique** (`basira-net`). Seul Caddy expose des ports vers l'extérieur (80/443).

```
┌─────────────────────────────────────────────────────────────┐
│                  Caddy  (reverse proxy / TLS)                │
│                   ports exposés : 80, 443                    │
└───────────────┬───────────────────────────┬─────────────────┘
                │                            │
         ┌──────▼──────┐              ┌──────▼──────┐
         │   frontend   │              │     api      │
         │ React + Vite │              │   FastAPI    │
         │   (Nginx)    │              │  SQLite WAL  │
         │   :80        │              │   :8000      │
         └─────────────┘              └──────┬───────┘
                                              │  (réseau interne, X-Internal-Secret)
          ┌───────────────────────────────────┼──────────────────────────┐
          │                                   │                          │
   ┌──────▼──────┐                    ┌───────▼──────┐          ┌────────▼──────┐
   │   poller     │  ──extract──►      │  extractor   │          │    scorer     │
   │ feedparser   │  ──score────►      │ trafilatura  │          │ Uni GPU /     │
   │ APScheduler  │                    │ readability  │          │ Ollama /      │
   │  (cron 6h)   │                    │ +SS metadata │          │ OpenRouter    │
   │  :pas exposé │                    │   :8001      │          │   :8002       │
   └─────────────┘                    └─────────────┘          └───────────────┘
```

**Volumes Docker :** `data` (SQLite + index ChromaDB sous `/data/chroma`), `caddy_data`, `caddy_config`.
**Dépendances externes obligatoires :** aucune. (Ollama tourne sur l'hôte via `host.docker.internal`.)

### Qui fait quoi — service par service

| Service | Rôle | Port interne | Tech clé | Exposé ? |
|---------|------|:---:|----------|:---:|
| **caddy** | Reverse proxy, terminaison TLS (Let's Encrypt auto en prod), routage front/API | 80/443 | `caddy:2-alpine` | ✅ 80/443 |
| **frontend** | SPA React servie statiquement, PWA installable | 80 | React/Vite build | ❌ |
| **api** | Cœur applicatif : REST, auth, SSE, DB, scheduler des tâches recherche | 8000 | FastAPI | ❌ |
| **poller** | Récupère les flux, déduplique, orchestre extraction → enrichissement → scoring | — | feedparser + APScheduler | ❌ |
| **extractor** | Extraction plein-texte + métadonnées Semantic Scholar | 8001 | trafilatura/readability | ❌ |
| **scorer** | Note l'article 0–10 + tags/résumé/dimensions recherche via LLM | 8002 | routage LLM 3-tiers | ❌ |

> Les services internes communiquent en HTTP sur le réseau Docker. Les appels poller/scorer → API sont authentifiés par le header `X-Internal-Secret` (valeur = `API_SECRET`).

---

## 4. Le pipeline de traitement (du flux à l'écran)

```
Flux RSS / arXiv / Semantic Scholar
        │
        ▼
  ① POLLER  (APScheduler, toutes les FETCH_INTERVAL_MINUTES ≈ 6h)
        │   • tri des entrées (récent d'abord)
        │   • filtre âge (MAX_ARTICLE_AGE_DAYS) + plafond (MAX_NEW_ARTICLES_PER_FEED)
        │   • déduplication 3 couches (voir §6)
        ▼
  ② EXTRACTOR  (/extract)
        │   • plein-texte via trafilatura → fallback readability
        │   • URL canonique (<link rel="canonical">)
        │   • métadonnées Semantic Scholar pour les papiers (arXiv/ACL/DOI)
        ▼
  ③ PAPER ENRICHER  (poller, appel Ollama léger, AVANT stockage)
        │   • classification abstract → contribution_type / re_document_type
        ▼
  ④ API  (/api/internal/articles)  → stockage SQLite
        ▼
  ⑤ SCORER  (/score, sérialisé par sémaphore global, 1 appel LLM à la fois)
        │   • score 0–10 · tags · résumé · reason
        │   • contribution_type · re_document_type · novelty · rigor · relevance
        │   • injecte le profil de préférences (feedback 👍/👎)
        ▼
  ⑥ EMBEDDER  (nomic-embed-text via Ollama)
        │   • vecteur → index ChromaDB (recherche sémantique + lit review)
        ▼
  ⑦ API + SQLite  ──SSE──►  Frontend React (livraison temps réel, sans refresh)
```

Le poller traite les flux **en parallèle** (`asyncio.gather`), mais le **scoring est sérialisé** par un `asyncio.Semaphore(1)` global + un délai `SCORE_DELAY_SECONDS` pour ne pas saturer le LLM. Tous les appels HTTP inter-services sont retentés (`tenacity`, backoff exponentiel, 3 essais).

---

## 5. Backend en détail

### 5.1 `api` — FastAPI (le cœur)

Point d'entrée : `backend/api/main.py`. Application factory FastAPI avec :
- **CORS** restreint à `CORS_ORIGIN`.
- **Logging structuré** JSON via `structlog`.
- **Lifecycle startup** : `init_db()`, purge des sessions expirées, nettoyage des vieux articles, **seed des flux par défaut** (`DEFAULT_FEEDS` — arXiv cs.SE/AI/CL…, ACL, OpenReview, blogs IA, Martin Fowler, HN…), **seed de la taxonomie recherche** (`_SEED_PROFILE` — 9 tiers pondérés 5.0 → 1.0 autour de « AI-driven MBSE / CPS / Requirements Engineering »), démarrage du scheduler.
- **Auth** : routes publiques `/auth/login`, `/auth/logout`, `/auth/status` ; sessions par cookie, rate-limiting par IP, vérification du mot de passe (`AUTH_PASSWORD`).
- **SSE** : `/api/stream` (protégé) pousse les nouveaux articles en temps réel (keepalive 30 s).
- **Health** : `/api/health` (public, utilisé par Docker/Caddy).

**Routers** (montés dans `main.py`, fichiers sous `backend/api/routers/`) :

| Router | Préfixe | Responsabilité |
|--------|---------|----------------|
| `articles.py` | `/api/articles` | Liste/détail, read/unread, bookmark, **related** (similarité sémantique), **feedback** 👍/👎 |
| `feeds.py` | `/api/feeds`, `/api/digest` | CRUD flux, **import OPML**, Daily Digest |
| `highlights.py` | `/api/articles/{id}/highlights` | Surlignages (couleur, note, section de thèse), bulk-update |
| `ask.py` | `/api/articles/{id}/ask` | **Ask-AI** : réponse LLM en streaming sur l'article lu |
| `stats.py` | `/api/stats` | Statistiques de lecture, **reading-debt** (dette de lecture), objectif hebdo |
| `research.py` | `/api/research` | **Le plus gros** : clusters, profil chercheur, lit review (in-corpus + externe), export ARISE, **threat monitor**, **author radar**, export surlignages, citations, **conference radar**, notifications, bibliographie BibTeX |
| `admin.py` | `/api/admin` | Maintenance : suppression articles cassés, normalisation d'URL |
| `internal.py` | `/api/internal` | **Endpoints inter-services** (protégés par `X-Internal-Secret`) : feeds, feedback-examples, articles/exists, création article, post-scoring |

**Modules métier** (`backend/api/`) :
- `database.py` — engine SQLAlchemy, `SessionLocal`, modèles ORM, `init_db()` (+ micro-migrations SQLite idempotentes).
- `auth.py` — sessions, cookies, rate-limit, hash mot de passe.
- `scheduler.py` — APScheduler des tâches recherche (threat scan, author scan, citation indexing…).
- `sse.py` — files par client + `broadcast_new_article`.
- `embedder.py` — embeddings nomic-embed-text + accès ChromaDB.
- `lit_review_llm.py`, `litreview_exporter.py` — synthèse lit review in-corpus + export Markdown.
- `external_review.py` — recherche état de l'art (Semantic Scholar + OpenAlex, rerank, synthèse).
- `bibliography.py`, `citation_indexer.py`, `author_radar.py`, `conferences.py` — fonctionnalités recherche dédiées.
- `models.py` — schémas Pydantic (entrées/sorties API).

### 5.2 `poller` — `backend/poller/main.py`

Orchestrateur d'ingestion (voir §4). Points notables :
- `normalize_url()` — forme canonique (lowercase, suppression `www.`, retrait des paramètres de tracking `utm_*`/`fbclid`/…, tri des paramètres, suppression slash final). Clé de déduplication.
- Garde-fous : `MAX_NEW_ARTICLES_PER_FEED` (5), `MAX_ARTICLE_AGE_DAYS` (7), `SCORE_DELAY_SECONDS` (2.0).
- `paper_enricher.py` — détecte une URL de papier (`is_paper_url`) et enrichit (`enrich_paper_meta`) **avant** stockage et scoring.

### 5.3 `extractor` — `backend/extractor/extractor.py`

Microservice FastAPI (`POST /extract`). Renvoie titre, `content_html`, `content_text`, images, auteur, `canonical_url`, `paper_meta`. Cascade trafilatura → readability ; échec non bloquant (l'article n'est jamais perdu, `extraction_failed=true`).

### 5.4 `scorer` — `backend/scorer/scorer.py`

Microservice FastAPI (`POST /score`). **Routage LLM à 3 niveaux**, dans l'ordre :

| Tier | Source | Quand |
|:---:|--------|-------|
| 1 | **GPU université** (API OpenAI-compatible) | si `UNI_OLLAMA_URL` + `UNI_OLLAMA_MODEL` + `UNI_OLLAMA_API_KEY` définis (VPN requis) |
| 2 | **OpenRouter** (cloud) | si `OPENROUTER_API_KEY` commence par `sk-` |
| 3 | **Ollama local** | fallback par défaut |

En dernier recours (aucun LLM joignable) : score neutre 5.0. La sortie JSON est extraite de façon robuste (`extract_json_from_text` gère markdown, préambule `<thinking>`, troncature par limite de tokens) puis validée/bornée (`validate_score_result`).

**Prompts de scoring** (`backend/scorer/prompts/`, **montés en volume** → éditables sans rebuild) :

| Profil (`PROMPT_PROFILE`) | Usage |
|---------|-------|
| `infra` | DevOps / platform engineering uniquement |
| `research` | Veille doctorale (récompense surveys, méthodes, benchmarks, théorie) |
| `unified` | **Défaut** — double mode, score correctement infra **et** papiers |

Le scorer construit aussi un **bloc de préférences** (`build_preference_block`) à partir de l'historique 👍/👎 (agrégation de fréquence des tags, structure contrastive liked/disliked, budget ~220 tokens, activé à partir de 3 interactions — approche LLM-Rec / NAACL 2024).

---

## 6. Modèle de données (SQLite WAL)

Défini dans `backend/shared/database.py`. Mode WAL + `synchronous=NORMAL` + `foreign_keys=ON`. Migrations légères idempotentes via `ALTER TABLE … ADD COLUMN` enveloppés en try/except.

**Tables principales :**

- **`feeds`** — `id, url (unique), name, category, active, last_fetched`.
- **`articles`** — colonnes clés :
  - Identité/contenu : `feed_id (FK)`, `title`, `url (unique)`, `published_at`, `author`, `content_html`, `content_text`, `images_json`.
  - Scoring : `score`, `tags_json`, `summary_bullets_json`, `reason`, `score_meta_json`.
  - État lecture : `read_at`, `bookmarked`, `extraction_failed`, `created_at`.
  - Déduplication : `title_fingerprint` (indexé, + index composite `(title_fingerprint, created_at)`).
  - Dimensions recherche : `contribution_type`, `re_document_type`, `paper_meta_json`.

D'autres tables (profil chercheur `research_profile`, surlignages, sessions, alertes threat, auteurs suivis, reviews littérature, etc.) sont gérées par les modules dédiés de `backend/api/`.

**Déduplication 3 couches** (poller) : (1) URL canonique normalisée, (2) `title_fingerprint`, (3) `<link rel="canonical">` extrait du HTML.

---

## 7. Frontend en détail (`frontend/`)

SPA **React 18 + TypeScript**, bundler **Vite 5**, **Tailwind CSS** (design system « ProjectOS », thème sombre natif), **PWA** (installable, offline). État global via **Zustand** ; listes virtualisées via **react-virtuoso** ; icônes **lucide-react**.

- **`src/main.tsx`** — bootstrap React + enregistrement service worker (PWA).
- **`src/App.tsx`** — gate d'authentification (`useAuth` → `/auth/status`), layout 3 panneaux (Sidebar / Topbar / contenu), routeur de vues local (`appView`), **raccourcis clavier** (`j/k`, `r`, `b`, `o`, `/`, `[`, `?`), connexion **SSE** et statut online/offline.

**Stores Zustand** (`src/store/`) : `articles.ts`, `highlights.ts`, `research.ts`, `stats.ts`.

**Hooks** (`src/hooks/`) : `useArticles`, `useSSE` (temps réel), `useOnlineStatus`, `usePolling`.

**Vues principales** (`appView`) : `feed`, `digest`, `stats`, `research` (clusters), `litreview`, `threats`, `authors`, `write`, `conferences`, `highlights`, `bibliography`.

**Composants notables** (`src/components/`) : `ArticleList`/`ArticleCard`/`ReaderView` (lecture, swipe, progression, police ajustable), `AskAIPanel`, `DigestView`, `LitReviewView`, `ResearchDigestView`, `ThreatView`, `AuthorRadarView`, `ConferenceRadar`, `HighlightManager`/`HighlightPopover`, `BibliographyPanel`, `RelatedPanel`, `ScoreBar`, badges (`ContribTypeBadge`, `ReDocTypeBadge`, `ThreatBadge`).

**Proxy API** : `frontend/functions/api/[[path]].ts` — Cloudflare Pages Function qui reverse-proxie `/api/*` vers le backend distant (`API_BASE_URL`) quand le front est déployé sur Cloudflare Pages (évite le CORS, masque l'URL backend).

---

## 8. Fonctionnalités recherche (différenciantes)

| Fonctionnalité | Description | Implémentation |
|----------------|-------------|----------------|
| **Daily Digest** | Top articles 24–72 h, paliers par score (≥5) | `/api/digest` |
| **Recherche sémantique** | Articles liés par similarité d'embedding | `embedder.py` + ChromaDB |
| **Clusters de sujets** | Regroupement de l'historique embarqué | AgglomerativeClustering / HDBSCAN |
| **Profil chercheur** | Store topic/method/domain, auto-mis à jour par feedback | `research_profile` (9 tiers) |
| **Lit review in-corpus** | Requête → retrieval sémantique → clustering → synthèse LLM par cluster → export MD | `lit_review_llm.py` |
| **État de l'art (externe)** | Semantic Scholar + OpenAlex → rerank (relevance 40 % / citations 35 % / récence 25 %) → synthèse + tableau comparatif + gaps + export MD | `external_review.py` |
| **Threat monitor** | Détecte les papiers qui chevauchent ta contribution de thèse | `research.py` (threats) |
| **Author radar** | Suit des auteurs Semantic Scholar et alerte sur nouveaux papiers | `author_radar.py` |
| **Citation graph** | Indexation des citations intra-corpus | `citation_indexer.py` |
| **Conference radar** | Deadlines des venues (à mettre à jour chaque septembre dans `conferences.py`) | `conferences.py` |
| **Export ARISE** | Export JSON structuré des papiers tagués RE | `models.py::build_arise_row` |
| **Bibliographie** | Export BibTeX | `bibliography.py` |

**Boucle de feedback** : 👍/👎 sur un article met à jour un profil de préférences structuré (agrégation par fréquence de tags sur tout l'historique), réinjecté dans chaque scoring suivant.

---

## 9. Configuration (`.env`)

Copier `.env.example` → `.env`. Variables clés (⚠️ **secrets jamais commités**) :

```bash
# ── LLM ───────────────────────────────────────────────
OPENROUTER_API_KEY=                # Fallback cloud (optionnel)
SCORER_MODEL=google/gemini-2.5-flash-lite
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_EMBED_MODEL=nomic-embed-text   # requis : recherche sémantique + lit review
UNI_OLLAMA_URL=                    # GPU université (OpenAI-compatible, VPN)
UNI_OLLAMA_MODEL=
UNI_OLLAMA_API_KEY=

# ── Scoring ──────────────────────────────────────────
PROMPT_PROFILE=unified             # infra | research | unified
SCORER_MAX_CHARS=6000              # doublé pour papiers confirmés (max 12000)

# ── Recherche littérature externe ────────────────────
SS_API_KEY=                        # optionnel (rate limit SS 1→10 req/s)
# OA_CONTACT_EMAIL=                # optionnel (polite pool OpenAlex)

# ── App ──────────────────────────────────────────────
DB_PATH=/data/basira.db
FETCH_INTERVAL_MINUTES=360
API_SECRET=<aléatoire>             # secret inter-services

# ── Auth ─────────────────────────────────────────────
AUTH_PASSWORD=<mot de passe fort>  # requis
HTTPS_ONLY=false                   # true en prod
CORS_ORIGIN=http://localhost

# ── Production ───────────────────────────────────────
CADDY_DOMAIN=reader.exemple.com    # active HTTPS automatique
```

---

## 10. Démarrer / déployer

### Local
```bash
cp .env.example .env          # configurer AUTH_PASSWORD (requis)
ollama pull nomic-embed-text  # modèle d'embedding (requis)
docker compose up -d --build
# → http://localhost
```

### Production (VPS)
```bash
cp .env.example .env
# Éditer : CADDY_DOMAIN, AUTH_PASSWORD, OPENROUTER_API_KEY, HTTPS_ONLY=true
docker compose up -d --build
# Caddy provisionne le TLS via Let's Encrypt automatiquement
```

### Front sur Cloudflare Pages (option)
GitHub Actions (`.github/workflows/deploy-pages.yml`) build le front et le déploie sur Cloudflare Pages. La Pages Function proxie `/api/*` vers `API_BASE_URL` (backend hébergé séparément). Voir `CLOUDFLARE_DEPLOY.md` et `DEPLOY.md`.

---

## 11. Tests

- **API** : `backend/api/test_clustering.py`.
- **Scorer & logique métier** : `backend/scorer/tests/` — `test_scorer_logic.py`, `test_arise_export.py`, `test_article_filters.py`, `test_cluster_map.py`, `test_database_migrations.py`, `test_literature_review.py`, `test_paper_enricher.py`, `test_researcher_profile.py`, `test_prompt.py`, `test_semantic_retrieval.py`.

```bash
cd backend && pytest          # suite complète
```

---

## 12. Notes de maintenance

- **Deadlines de conférences** — mettre à jour `backend/api/conferences.py` chaque septembre (nouveaux cycles).
- **Prompts de scoring** — `backend/scorer/prompts/*.md` montés en volume : éditer sans rebuild.
- **Modèle d'embedding** — `ollama pull nomic-embed-text` requis sur l'hôte Ollama.

---

## 13. Carte mentale « qui appelle qui »

```
Navigateur ──► Caddy ──► frontend (statique)
                  └────► api  ──► SQLite
                                └► ChromaDB (embeddings)
                                └► Ollama (Ask-AI, embeddings)
                                └► Semantic Scholar / OpenAlex (état de l'art)

poller ──(cron)──► extractor ──► api
       └─────────► scorer ──► (Uni GPU | OpenRouter | Ollama) ──► api
```

---

<div align="center"><em>بَصِيرَة — perspicacité</em></div>
