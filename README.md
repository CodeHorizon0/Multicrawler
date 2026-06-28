# MultiCrawler

A fast, asynchronous web crawler built for modern websites.

MultiCrawler combines a high-performance HTTP client with browser automation to crawl both traditional and JavaScript-heavy websites. It supports HTTP/1.1, HTTP/2, and HTTP/3, extracts links from a wide range of HTML sources, and stores crawl results in a structured, resumable format.

## Features

### Networking

- HTTP/1.1, HTTP/2 and HTTP/3 support
- Automatic protocol selection
- Persistent connection pooling
- Reusable HTTP sessions
- Reusable browser sessions
- Redirect handling
- Cookie persistence
- Configurable request timeouts
- Custom request headers and User-Agent

### Browser Integration

When a page requires JavaScript execution or HTTP/3, MultiCrawler transparently switches to Playwright.

Instead of creating a new browser for every request, a single browser instance is reused throughout the crawl, significantly reducing startup overhead.

### HTML Processing

The built-in parser extracts URLs from much more than just anchor tags.

Supported sources include:

- `<a>`
- `<img>`
- `<script>`
- `<link>`
- `<iframe>`
- `<frame>`
- `<source>`
- `<video>`
- `<audio>`
- `<embed>`
- `<object>`
- `<form>`
- `srcset`
- inline CSS
- `style` attributes
- `<meta http-equiv="refresh">`
- JSON-LD
- JavaScript URL candidates
- protocol-relative URLs
- relative URLs
- `<base href>` resolution

### Performance

Designed for large crawls.

Key optimizations include:

- fully asynchronous architecture
- reusable network sessions
- multiprocessing HTML parsing
- URL deduplication
- concurrent workers
- SQLite checkpoints
- resumable crawling
- graceful shutdown
- forced cancellation on repeated Ctrl+C

### Storage

Downloaded content is organized by domain.

Example:

```text
data/
├── example.com/
│   ├── index.html
│   ├── index.mhtml
│   └── metadata.json
└── github.com/
    ├── page.html
    └── metadata.json
```

---

## Requirements

- Python **3.13.5**
- Playwright
- httpx
- SQLite

---

## Installation

```bash
git clone https://github.com/yourname/multicrawler.git

cd multicrawler

python -m venv .venv

source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright browsers:

```bash
playwright install
```

---

## Quick Start

Crawl a website:

```bash
python -m multicrawler \
    --seed https://example.com \
    --data-dir ./data
```

Limit the crawl to 100 pages:

```bash
python -m multicrawler \
    --seed https://example.com \
    --max-pages 100
```

Limit crawl depth:

```bash
python -m multicrawler \
    --seed https://example.com \
    --max-depth 3
```

Limit extracted links per page:

```bash
python -m multicrawler \
    --seed https://example.com \
    --max-links-per-page 200
```

Limit queue size:

```bash
python -m multicrawler \
    --seed https://example.com \
    --max-queue-size 1000
```

Enable MHTML snapshots:

```bash
python -m multicrawler \
    --seed https://example.com \
    --save-mhtml
```

Run with multiple workers:

```bash
python -m multicrawler \
    --seed https://example.com \
    --workers 32
```

Resume a previous crawl:

```bash
python -m multicrawler --resume
```

Example of a larger crawl:

```bash
python -m multicrawler \
    --seed https://example.com \
    --workers 32 \
    --max-pages 10000 \
    --max-depth 6 \
    --max-links-per-page 300 \
    --max-queue-size 50000 \
    --save-mhtml \
    --resume
```

---

## Graceful Shutdown

Pressing **Ctrl+C** stops scheduling new work while allowing active downloads to finish safely.

During shutdown, MultiCrawler:

- stops scheduling new URLs
- finishes active requests
- writes checkpoint data
- closes HTTP sessions
- shuts down the browser
- exits cleanly

Pressing **Ctrl+C** again immediately cancels all remaining tasks.

---

## Project Structure

```text
multicrawler/
├── cli/
├── crawler/
├── downloader/
├── html/
├── browser/
├── storage/
├── utils/
└── ...
```

---

## Architecture

```text
                CLI
                 │
                 ▼
           Crawl Scheduler
                 │
      ┌──────────┴──────────┐
      │                     │
      ▼                     ▼
 HTTP Client          Browser Client
   (httpx)            (Playwright)
      │                     │
      └──────────┬──────────┘
                 ▼
          Content Downloader
                 ▼
            HTML Parser
                 ▼
          Link Extraction
                 ▼
             URL Queue
                 ▼
      SQLite Checkpoint Store
                 ▼
          File System Storage
```

---

## Highlights

- Modern asynchronous architecture
- HTTP/3 support
- HTTP/2 support
- Browser fallback for dynamic pages
- Intelligent HTML parsing
- Persistent sessions
- MHTML snapshots
- Resumable crawling
- SQLite checkpoints
- High-performance concurrent crawling

