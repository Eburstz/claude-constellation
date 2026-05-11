#!/usr/bin/env python3
"""
claude-constellation: a beautiful interactive mind map of every conversation
you've ever had with Claude — across Claude Code, Cowork, and claude.ai web chat.

Usage:
    python3 claude_constellation.py
    python3 claude_constellation.py --output ~/Desktop/my-graph.html
    python3 claude_constellation.py --web-export ~/Downloads/data-2026-05-10.zip
    python3 claude_constellation.py --code ~/.claude/projects --web-export ~/Downloads/claude-export.zip

By default scans ~/.claude/projects/ for Claude Code and Cowork transcripts.
If you provide --web-export, it also includes your claude.ai chat history
(get the zip from claude.ai → Settings → Privacy → Export Data).

Everything runs locally. Nothing is sent anywhere — your conversations stay
on your machine.
"""

import argparse
import json
import math
import os
import re
import sys
import urllib.error
import urllib.request
import zipfile
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

# Optional embedding backends — graceful fallback to TF-IDF if neither installed.
try:
    from fastembed import TextEmbedding as _FastEmbed
    _HAS_FASTEMBED = True
except Exception:
    _HAS_FASTEMBED = False

try:
    from sentence_transformers import SentenceTransformer as _STModel
    _HAS_ST = True
except Exception:
    _HAS_ST = False

CACHE_DIR = Path.home() / ".cache" / "claude-constellation"

# -----------------------------------------------------------------------------
# Topic extraction
# -----------------------------------------------------------------------------

TOPIC_HINTS = {
    "auth":       ["auth", "login", "jwt", "oauth", "session", "password"],
    "api":        ["api", "endpoint", "rest", "graphql"],
    "react":      ["react", "tsx", "jsx", "useeffect", "usestate", "component"],
    "typescript": ["typescript", "interface ", "generic"],
    "python":     ["python", "django", "flask", "fastapi", "pip "],
    "database":   ["postgres", "sqlite", "mysql", "schema", "migration", " sql "],
    "css":        ["css", "tailwind", "styled", "padding", "margin"],
    "build":      ["webpack", "vite", "rollup", "esbuild"],
    "test":       ["test", "jest", "vitest", "playwright", "cypress"],
    "deploy":     ["deploy", "docker", "kubernetes", "vercel", "netlify"],
    "git":        ["git ", "commit", "branch", "merge", "rebase", "pull request"],
    "design":     ["design", "figma", "layout", "color", " ui ", " ux "],
    "data":       ["csv", "parse", "scrape", "etl", "pandas", "dataset"],
    "ai":         ["llm", "openai", "anthropic", "claude", "gpt", "embedding", "prompt", "agent"],
    "perf":       ["perf", "optimize", "slow", "cache", "memory leak"],
    "bug":        ["bug", "error", "fail", "crash", " fix"],
    "refactor":   ["refactor", "rename", "rewrite", "cleanup"],
    "viz":        ["graph", "chart", "visualization", " d3 ", "plot", "mind map"],
    "crypto":     ["crypto", "bitcoin", "ethereum", "wallet", "blockchain", "nft", "web3"],
    "writing":    ["draft", "blog", "newsletter", "essay", "article"],
    "planning":   ["plan", "roadmap", "todo", "priorit"],
    "security":   ["security", "vulnerab", "exploit", "sanitize", "csrf"],
    "mobile":     ["ios", "android", "swift", "react native", "expo"],
    "devops":     ["ci ", " cd ", "github actions", "pipeline"],
    "math":       ["algorithm", "matrix", "calculus", "regression"],
    "render":     ["render", "svg", "canvas", "webgl", "shader"],
    "email":      ["email", "newsletter", "smtp", "transactional"],
    "marketing":  ["marketing", "landing", "seo", "ads ", "campaign"],
    "product":    ["product", "feature", "user", "customer", "feedback"],
    "research":   ["research", "study", "paper", "literature"],
    "personal":   ["recipe", "travel", "workout", "fitness", "vacation", "hobby"],
}


def extract_topics(text: str, k: int = 6) -> list:
    text_l = text.lower()
    scores = {}
    for topic, hints in TOPIC_HINTS.items():
        s = sum(text_l.count(h) for h in hints)
        if s > 0:
            scores[topic] = s
    return [t for t, _ in sorted(scores.items(), key=lambda x: -x[1])[:k]]


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------

def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def decode_project(dir_name: str) -> str:
    """Claude Code encodes cwd by replacing / with -. Return a readable last segment.
    Strips Claude Code worktree suffixes and iCloud sync noise so projects roll up nicely."""
    s = dir_name.lstrip("-")
    # `proj--claude-worktrees-foo` → `proj`
    s = re.split(r"--claude-worktrees", s, maxsplit=1)[0].rstrip("-")
    # Strip iCloud's Mobile-Documents path so an iCloud-synced Desktop folds into "Desktop"
    s = re.sub(r"-Mobile-Documents-com-apple-CloudDocs", "", s)
    parts = s.split("-")
    for anchor in ("Desktop", "Documents", "Projects", "src", "code", "Repos", "repos", "dev"):
        if anchor in parts:
            idx = len(parts) - 1 - parts[::-1].index(anchor)
            tail = parts[idx + 1:]
            if tail:
                return "-".join(tail)
            # Anchor itself is the leaf → use it as the project name
            return anchor
    return parts[-1] if parts else dir_name


def clean_title(title: str) -> str:
    t = title.strip()
    t = re.sub(r"^\s*</?[^>]+>\s*", "", t)
    t = re.sub(r"<[^>]+>.*?</[^>]+>", "", t, flags=re.DOTALL)
    t = re.sub(r"<[^>]+/>", "", t)
    t = re.sub(r"^\s*@\S+\s+", "", t)
    t = re.sub(r"^\s*[`'\"]+", "", t)
    t = re.sub(r"\s+", " ", t)
    t = t.strip()
    if not t or len(t) < 4:
        return "Untitled session"
    return t[0].upper() + t[1:]


def derive_title(user_msgs: list, fallback: str) -> str:
    for m in user_msgs:
        t = clean_title(m)
        if not t or t == "Untitled session":
            continue
        first = t.split("\n")[0].strip()
        if len(first) > 90:
            first = first[:88].rstrip() + "…"
        if first:
            return first
    return fallback


def short_summary(text: str, char_budget: int = 280) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    out, used = [], 0
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if used + len(s) > char_budget and out:
            break
        out.append(s)
        used += len(s)
        if len(out) >= 3:
            break
    return " ".join(out)[:char_budget + 20]


# -----------------------------------------------------------------------------
# Crawler: Claude Code / Cowork (~/.claude/projects/*/<session>.jsonl)
# -----------------------------------------------------------------------------

def extract_text_from_record(rec) -> str:
    msg = rec.get("message")
    if not msg:
        return ""
    content = msg.get("content") if isinstance(msg, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                out.append(block["text"])
        return " ".join(out)
    return ""


def process_local_session_file(jsonl_path: Path, project: str, gap_hours: float) -> list:
    """Read one .jsonl, return list of arc dicts (split on user-idle gaps).
    For sessions with no real user/assistant content but a `last-prompt` record,
    emit a single 'stub' arc so the conversation still appears as a faint star."""
    session_id = jsonl_path.stem
    records = []
    ai_title = None
    last_prompt = None
    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("type") == "ai-title" and not ai_title:
                    ai_title = (rec.get("aiTitle") or "").strip()
                    continue
                if rec.get("type") == "last-prompt" and not last_prompt:
                    last_prompt = (rec.get("lastPrompt") or "").strip()
                    continue
                t = rec.get("type")
                if t not in ("user", "assistant"):
                    continue
                txt = extract_text_from_record(rec)
                if not txt or len(txt.strip()) < 2:
                    continue
                records.append((parse_ts(rec.get("timestamp")), t, txt))
    except (PermissionError, FileNotFoundError):
        return []

    # Empty session that still has a `last-prompt` → emit a single stub arc
    if not records:
        if last_prompt:
            mtime = datetime.fromtimestamp(jsonl_path.stat().st_mtime)
            return [{
                "id": f"local:{session_id}",
                "title": clean_title(ai_title or last_prompt),
                "source": "Local",
                "project": project,
                "ai_title": ai_title,
                "date": mtime.isoformat()[:10],
                "last_date": mtime.isoformat()[:10],
                "messages": 1,
                "topics": extract_topics(last_prompt, k=4),
                "summary_seed": last_prompt[:600],
                "preview": last_prompt[:240],
            }]
        return []

    # Split into arcs separated by user-idle gaps
    arcs = []
    current = []
    last_user_ts = None
    for ts, role, txt in records:
        if role == "user" and ts is not None:
            if last_user_ts and (ts - last_user_ts).total_seconds() > gap_hours * 3600:
                if current:
                    arcs.append(current)
                current = []
            last_user_ts = ts
        current.append((ts, role, txt))
    if current:
        arcs.append(current)

    out = []
    for i, arc in enumerate(arcs):
        user_msgs = [t for _, r, t in arc if r == "user"]
        assistant_msgs = [t for _, r, t in arc if r == "assistant"]
        if not user_msgs:
            continue
        timestamps = [ts for ts, _, _ in arc if ts is not None]
        full_text = " ".join([t for _, _, t in arc])
        if len(arcs) == 1 and ai_title:
            title = ai_title
        else:
            title = derive_title(user_msgs, ai_title or project)
        arc_id = f"local:{session_id}" if len(arcs) == 1 else f"local:{session_id}:{i}"
        out.append({
            "id": arc_id,
            "title": clean_title(title),
            "source": "Local",  # refined later
            "project": project,
            "ai_title": ai_title,
            "date": (min(timestamps).isoformat()[:10] if timestamps else "1970-01-01"),
            "last_date": (max(timestamps).isoformat()[:10] if timestamps else "1970-01-01"),
            "messages": len(user_msgs) + len(assistant_msgs),
            "topics": extract_topics(full_text),
            "summary_seed": " ".join(user_msgs)[:600],
            "preview": (user_msgs[0][:240] if user_msgs else ""),
        })
    return out


def crawl_local(code_root: Path, gap_hours: float) -> list:
    """Walk ~/.claude/projects/ for Claude Code + Cowork shared storage."""
    sessions = []
    if not code_root.exists():
        print(f"  (no directory at {code_root} — skipping local crawl)")
        return []
    for proj_dir in sorted(code_root.iterdir()):
        if not proj_dir.is_dir():
            continue
        project = decode_project(proj_dir.name)
        for jsonl_path in sorted(proj_dir.rglob("*.jsonl")):
            arcs = process_local_session_file(jsonl_path, project, gap_hours)
            sessions.extend(arcs)
    return sessions


# -----------------------------------------------------------------------------
# Crawler: claude.ai data export
# -----------------------------------------------------------------------------

def find_conversations_json(path: Path) -> Path | None:
    """Locate conversations.json inside an unzipped export folder."""
    if path.is_file() and path.name == "conversations.json":
        return path
    if path.is_dir():
        for candidate in path.rglob("conversations.json"):
            return candidate
    return None


def crawl_web_export(export_path: Path) -> list:
    """Parse a claude.ai data export — accepts a zip or a directory."""
    if not export_path.exists():
        print(f"  (no path at {export_path} — skipping web export)")
        return []

    convs_json = None
    tmpdir = None
    try:
        if export_path.suffix == ".zip":
            tmpdir = tempfile.mkdtemp(prefix="claude-export-")
            with zipfile.ZipFile(export_path) as zf:
                zf.extractall(tmpdir)
            convs_json = find_conversations_json(Path(tmpdir))
        else:
            convs_json = find_conversations_json(export_path)

        if not convs_json:
            print(f"  (no conversations.json found in {export_path})")
            return []

        with open(convs_json, "r", encoding="utf-8") as f:
            data = json.load(f)
    finally:
        if tmpdir and Path(tmpdir).exists():
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    sessions = []
    for conv in data:
        uuid = conv.get("uuid") or conv.get("id") or ""
        if not uuid:
            continue
        name = (conv.get("name") or "").strip()
        created = conv.get("created_at") or ""
        updated = conv.get("updated_at") or created
        msgs = conv.get("chat_messages") or conv.get("messages") or []
        if not msgs:
            continue

        user_msgs, assistant_msgs = [], []
        full_chunks = []
        for m in msgs:
            sender = (m.get("sender") or m.get("role") or "").lower()
            text = m.get("text") or m.get("content") or ""
            if isinstance(text, list):
                text = " ".join(b.get("text", "") for b in text if isinstance(b, dict))
            if not text or not isinstance(text, str):
                continue
            if sender in ("human", "user"):
                user_msgs.append(text)
                full_chunks.append(text)
            elif sender in ("assistant", "ai"):
                assistant_msgs.append(text)
                full_chunks.append(text)

        if not user_msgs:
            continue

        full_text = " ".join(full_chunks)
        title = clean_title(name) if name else derive_title(user_msgs, "Web chat")

        sessions.append({
            "id": f"web:{uuid}",
            "title": title,
            "source": "Web",
            "project": "",
            "ai_title": name,
            "date": (created[:10] if created else "1970-01-01"),
            "last_date": (updated[:10] if updated else (created[:10] if created else "1970-01-01")),
            "messages": len(user_msgs) + len(assistant_msgs),
            "topics": extract_topics(full_text),
            "summary_seed": " ".join(user_msgs)[:600],
            "preview": (user_msgs[0][:240] if user_msgs else ""),
        })
    return sessions


# -----------------------------------------------------------------------------
# Source attribution + clustering
# -----------------------------------------------------------------------------

def attribute_source(node: dict) -> str:
    """Refine 'Local' into 'Code' or 'Cowork'. Cowork sessions are the ones that
    have an ai-generated title (`ai-title` records); plain Claude Code sessions
    do not. This holds across short and long sessions alike."""
    if node["source"] != "Local":
        return node["source"]
    if node.get("ai_title"):
        return "Cowork"
    return "Code"


# Visual palette — 8 distinct ramps. We pick the first N for whichever clusters end up active.
CLUSTER_PALETTE = [
    {"color": "#5fd8e8", "light": "#aef0fa"},  # cyan
    {"color": "#e85cb1", "light": "#f6a9d3"},  # magenta
    {"color": "#9ee85c", "light": "#cef39c"},  # lime
    {"color": "#a78bff", "light": "#d9c9ff"},  # violet
    {"color": "#e8b85c", "light": "#f6dca0"},  # amber
    {"color": "#5cd8a7", "light": "#a0f0d0"},  # teal
    {"color": "#ff8a5c", "light": "#ffc299"},  # coral
    {"color": "#d8e85c", "light": "#f0f6a0"},  # chartreuse
    {"color": "#ff5c93", "light": "#ff9bbb"},  # pink
    {"color": "#3ce8e0", "light": "#7af2ed"},  # aqua
    {"color": "#b78a3a", "light": "#d6b072"},  # bronze
    {"color": "#7e89c0", "light": "#aab2db"},  # slate
]


# -----------------------------------------------------------------------------
# Semantic analysis — TF-IDF, cosine similarity, label-propagation clustering
# -----------------------------------------------------------------------------

STOPWORDS = set((
    "the a an and or but if then so as is are was were be been being have has had do does did doing "
    "of in on at by for with to from this that these those it its they them their i me my we us our "
    "you your he she his her him about what when where why how which who not no yes up down out into "
    "over under again further once here there all any each few more most other some such only own "
    "same than too very can will just don should now also would could should one two three thing "
    "things just like really actually basically maybe make made get got give gave take took going "
    "want need think thought know knew see saw look looked use used way ways something anything "
    "nothing everything someone anyone everyone please thanks help via using"
).split())


def _tokenize(text: str) -> list:
    text = text.lower()
    return re.findall(r"\b[a-z][a-z0-9_-]{2,}\b", text)


def tfidf_vectors(docs: list) -> list:
    """Return list of dict {term: tfidf_score} for each document."""
    tokens_per_doc = [_tokenize(d) for d in docs]
    df = Counter()
    for tokens in tokens_per_doc:
        for t in set(tokens):
            df[t] += 1
    n = len(docs)
    if n == 0:
        return []
    max_df = max(3, int(n * 0.6))
    vectors = []
    for tokens in tokens_per_doc:
        filtered = [t for t in tokens if t not in STOPWORDS and 2 <= df[t] <= max_df]
        if not filtered:
            vectors.append({})
            continue
        tf = Counter(filtered)
        total = sum(tf.values())
        v = {}
        for term, count in tf.items():
            v[term] = (count / total) * math.log(n / df[term])
        norm = math.sqrt(sum(s * s for s in v.values()))
        if norm > 0:
            v = {t: s / norm for t, s in v.items()}
        vectors.append(v)
    return vectors


def cosine_sim(v1: dict, v2: dict) -> float:
    if not v1 or not v2:
        return 0.0
    if len(v1) > len(v2):
        v1, v2 = v2, v1
    return sum(v1.get(t, 0.0) * v2.get(t, 0.0) for t in v1)


def top_k_neighbors(vectors: list, k: int = 6, min_sim: float = 0.05) -> list:
    """For each doc i, return [(sim, j), ...] for top-k most similar."""
    n = len(vectors)
    out = []
    for i in range(n):
        sims = []
        for j in range(n):
            if i == j:
                continue
            s = cosine_sim(vectors[i], vectors[j])
            if s >= min_sim:
                sims.append((s, j))
        sims.sort(reverse=True)
        out.append(sims[:k])
    return out


def label_propagation(neighbors: list, max_iter: int = 30) -> list:
    """Standard label-propagation community detection on a weighted kNN graph."""
    import random
    rng = random.Random(42)
    n = len(neighbors)
    label = list(range(n))
    for _ in range(max_iter):
        order = list(range(n))
        rng.shuffle(order)
        changed = False
        for i in order:
            counts = Counter()
            for sim, j in neighbors[i]:
                counts[label[j]] += sim
            if not counts:
                continue
            best, _ = max(counts.items(), key=lambda x: (x[1], -x[0]))
            if best != label[i]:
                label[i] = best
                changed = True
        if not changed:
            break
    return label


# -----------------------------------------------------------------------------
# Dense embeddings (fastembed → sentence-transformers → None)
# -----------------------------------------------------------------------------

_EMBEDDER = None
_EMBEDDER_NAME = None


def get_embedder():
    """Return (encode_fn, name) or (None, None) if no embedding backend installed."""
    global _EMBEDDER, _EMBEDDER_NAME
    if _EMBEDDER is not None:
        return _EMBEDDER, _EMBEDDER_NAME
    if _HAS_FASTEMBED:
        try:
            em = _FastEmbed("BAAI/bge-small-en-v1.5")
            def encode(texts):
                return [list(v) for v in em.embed(list(texts))]
            _EMBEDDER, _EMBEDDER_NAME = encode, "fastembed/bge-small-en-v1.5"
            return _EMBEDDER, _EMBEDDER_NAME
        except Exception as e:
            print(f"  (fastembed init failed: {e})", file=sys.stderr)
    if _HAS_ST:
        try:
            em = _STModel("all-MiniLM-L6-v2")
            def encode(texts):
                return em.encode(list(texts)).tolist()
            _EMBEDDER, _EMBEDDER_NAME = encode, "sentence-transformers/all-MiniLM-L6-v2"
            return _EMBEDDER, _EMBEDDER_NAME
        except Exception as e:
            print(f"  (sentence-transformers init failed: {e})", file=sys.stderr)
    return None, None


def cosine_dense(a, b):
    if not a or not b:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def embed_documents(docs: list, cache_key: str = None):
    """Compute dense embeddings for `docs`, caching to ~/.cache/.
    Returns (vectors, backend_name) or (None, None) if no backend available."""
    encode, name = get_embedder()
    if not encode:
        return None, None
    if cache_key:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = CACHE_DIR / f"embed_{cache_key}.json"
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text())
                if cached.get("backend") == name and cached.get("count") == len(docs):
                    return cached["vectors"], name
            except Exception:
                pass
    vectors = encode(docs)
    if cache_key:
        try:
            cache_path.write_text(json.dumps({
                "backend": name, "count": len(docs), "vectors": vectors
            }))
        except Exception:
            pass
    return vectors, name


def top_k_neighbors_dense(vectors: list, k: int = 6, min_sim: float = 0.30) -> list:
    n = len(vectors)
    out = []
    for i in range(n):
        sims = []
        vi = vectors[i]
        for j in range(n):
            if i == j:
                continue
            s = cosine_dense(vi, vectors[j])
            if s >= min_sim:
                sims.append((s, j))
        sims.sort(reverse=True)
        out.append(sims[:k])
    return out


# -----------------------------------------------------------------------------
# LLM cluster naming via Anthropic API (Claude Haiku)
# -----------------------------------------------------------------------------

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def name_cluster_with_llm(member_titles: list, member_topics: list = None) -> str:
    """Ask Haiku for a concise 2-4 word cluster name. Returns None on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    titles = "\n".join(f"- {t}" for t in member_titles[:12])
    topics_block = ""
    if member_topics:
        topics_block = "\n\nRecurring topic words: " + ", ".join(member_topics[:10])
    prompt = (
        "Here are conversation titles from a single semantic cluster of someone's "
        "Claude chat history. Give me a concise topic name (2-4 words, sentence "
        "case, no quotes or punctuation) that captures what these chats are about.\n\n"
        f"Titles:\n{titles}{topics_block}\n\nTopic name:"
    )
    body = json.dumps({
        "model": HAIKU_MODEL,
        "max_tokens": 24,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        ANTHROPIC_API_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        text = data.get("content", [{}])[0].get("text", "").strip()
        text = re.sub(r"[\"'`]", "", text)
        text = text.split("\n")[0].strip().rstrip(".")
        if 2 <= len(text) <= 60:
            return text
    except Exception:
        return None
    return None


def name_clusters_with_llm(clusters: list, nodes: list) -> dict:
    """For each cluster, replace .name with an LLM-generated label. Caches to disk.
    Returns a {cluster_id: name} mapping (always returns, even if API key missing)."""
    cache_path = CACHE_DIR / "cluster_names.json"
    cache = {}
    if cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text())
        except Exception:
            cache = {}
    out = {}
    by_cluster = defaultdict(list)
    for n in nodes:
        by_cluster[n["cluster"]].append(n)

    for c in clusters:
        members = by_cluster.get(c["id"], [])
        members.sort(key=lambda x: x.get("messages", 0), reverse=True)
        titles = [m["title"] for m in members[:12]]
        all_topics = []
        for m in members[:30]:
            all_topics.extend(m.get("topics", []))
        topic_freq = [t for t, _ in Counter(all_topics).most_common(10)]
        # Cache key incorporates titles so name updates if cluster contents change a lot
        cache_key = c["id"] + ":" + str(hash(tuple(titles[:5])))
        if cache_key in cache:
            out[c["id"]] = cache[cache_key]
            continue
        name = name_cluster_with_llm(titles, topic_freq)
        if name:
            out[c["id"]] = name
            cache[cache_key] = name
    if out:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache, indent=2))
        except Exception:
            pass
    return out


def cluster_top_terms(vectors: list, communities: list, top_k: int = 4) -> dict:
    """For each community, sum tf-idf vectors of its members; return top-K terms."""
    by_comm = defaultdict(lambda: Counter())
    sizes = Counter(communities)
    for i, c in enumerate(communities):
        for term, score in vectors[i].items():
            by_comm[c][term] += score
    # Penalize terms that appear strongly in many communities (low distinctiveness)
    term_global = Counter()
    for c, terms in by_comm.items():
        for t in terms:
            term_global[t] += 1
    out = {}
    for c, terms in by_comm.items():
        scored = []
        for t, s in terms.items():
            distinctiveness = 1.0 / max(1, term_global[t] - 1)
            scored.append((s * (1 + distinctiveness), t))
        scored.sort(reverse=True)
        out[c] = [t for _, t in scored[:top_k]]
    return out


def assign_clusters(nodes: list, max_clusters: int = 12, knn: int = 6,
                    use_embeddings: bool = True) -> tuple:
    """Cluster conversations by semantic similarity.

    Tries dense embeddings (fastembed → sentence-transformers) first; falls back to
    TF-IDF if no backend installed. Builds kNN graph, runs label propagation,
    caps at `max_clusters` (rest → 'other').

    Returns (clusters, vectors, neighbors) — vectors/neighbors reused for edge build."""
    docs = []
    for n in nodes:
        parts = [
            n.get("title", "") or "",
            n.get("title", "") or "",  # title weighted 2x
            " ".join(n.get("topics", []) or []),
            n.get("preview", "") or "",
            n.get("summary_seed", "") or "",
        ]
        if n.get("project"):
            parts.append(("project_" + re.sub(r"\W+", "_", n["project"]).lower()) * 3)
        docs.append(" ".join(p for p in parts if p))

    vectors = None
    backend = None
    if use_embeddings:
        # Cache key: count + hash of doc lengths so refreshes with same nodes hit cache
        ck = f"docs_{len(docs)}_{abs(hash(tuple(len(d) for d in docs))) % 10**10}"
        vectors, backend = embed_documents(docs, cache_key=ck)
        if vectors:
            print(f"  embeddings: {backend}")
            neighbors = top_k_neighbors_dense(vectors, k=knn, min_sim=0.30)
        else:
            print("  no embedding backend installed — falling back to TF-IDF")
            print("  install with:  pip install fastembed   (or sentence-transformers)")
    if not vectors:
        vectors = tfidf_vectors(docs)
        neighbors = top_k_neighbors(vectors, k=knn, min_sim=0.05)
        backend = "tf-idf"
    communities = label_propagation(neighbors)

    # Cap to top-N largest, merge the rest into "other"
    counts = Counter(communities)
    big = {c for c, _ in counts.most_common(max_clusters)}
    final = [c if c in big else -1 for c in communities]  # -1 = other

    # Top-terms naming only works when vectors are sparse dicts (TF-IDF).
    # For dense embeddings we'll rely on the LLM naming pass + a numeric placeholder.
    if backend == "tf-idf":
        top_terms = cluster_top_terms(vectors, final)
    else:
        top_terms = {}

    cluster_keys = []
    seen = set()
    for c in final:
        if c not in seen:
            cluster_keys.append(c)
            seen.add(c)

    clusters = []
    for i, key in enumerate(cluster_keys):
        palette = CLUSTER_PALETTE[i % len(CLUSTER_PALETTE)]
        if key == -1:
            name = "Other"
        elif key in top_terms:
            terms = top_terms.get(key, [])
            cleaned = [t for t in terms if not t.startswith("project_")][:2]
            name = " · ".join(t.title() for t in cleaned) if cleaned else f"Cluster {i + 1}"
        else:
            name = f"Cluster {i + 1}"  # placeholder, LLM rename to follow
        clusters.append({
            "id": str(key),
            "name": name,
            "color": palette["color"],
            "light": palette["light"],
        })

    for i, n in enumerate(nodes):
        n["cluster"] = str(final[i])

    return clusters, vectors, neighbors


def _humanize_cluster_name(key: str) -> str:
    if key == "other":
        return "Other"
    # Dashes/underscores → spaces, capitalize words
    s = re.sub(r"[-_]+", " ", key).strip()
    return " ".join(w.capitalize() if w.islower() else w for w in s.split()) or key


# -----------------------------------------------------------------------------
# Edge construction
# -----------------------------------------------------------------------------

def build_edges(nodes: list, neighbors: list = None, max_semantic: int = 35,
                min_cross_sim: float = 0.22, intra_k: int = 2) -> list:
    """Build the connection graph — kept lean to avoid visual clutter.

    - intra-cluster: top-`intra_k` most similar same-cluster neighbors per node
    - cross-cluster: top `max_semantic` semantic-similarity bridges above `min_cross_sim`
    No more temporal-arc edges (they were redundant with intra-cluster similarity).
    """
    edges = []
    seen = set()
    id_for = [n["id"] for n in nodes]

    def add_edge(i, j, weight, kind):
        if i == j:
            return
        key = (min(i, j), max(i, j))
        if key in seen:
            return
        seen.add(key)
        edges.append({
            "source": id_for[i], "target": id_for[j],
            "weight": float(weight), "type": kind,
        })

    if not neighbors:
        return edges

    # 1) Intra-cluster — only the top-K strongest same-cluster neighbors per node
    for i, nbrs in enumerate(neighbors):
        same_c = [(s, j) for s, j in nbrs if nodes[j]["cluster"] == nodes[i]["cluster"]]
        for s, j in same_c[:intra_k]:
            add_edge(i, j, weight=s, kind="intra")

    # 2) Cross-cluster bridges — global top-N strongest, dedup
    candidates = []
    for i, nbrs in enumerate(neighbors):
        for s, j in nbrs:
            if nodes[j]["cluster"] != nodes[i]["cluster"] and s >= min_cross_sim:
                if i < j:
                    candidates.append((s, i, j))
    candidates.sort(reverse=True)
    for s, i, j in candidates[:max_semantic]:
        add_edge(i, j, weight=s, kind="bridge")

    return edges


# -----------------------------------------------------------------------------
# Repeat-question detection + bridge node tagging
# -----------------------------------------------------------------------------

def detect_repeat_questions(nodes: list, threshold: float = 0.42) -> dict:
    """Group conversations whose opening user prompts are very similar.
    Returns dict {node_id: [(other_id, similarity), ...]}."""
    docs = [(n.get("preview", "") or "") for n in nodes]
    vectors = tfidf_vectors(docs)
    out = defaultdict(list)
    for i in range(len(nodes)):
        if not vectors[i]:
            continue
        for j in range(i + 1, len(nodes)):
            if not vectors[j]:
                continue
            s = cosine_sim(vectors[i], vectors[j])
            if s >= threshold:
                out[nodes[i]["id"]].append((nodes[j]["id"], round(s, 3)))
                out[nodes[j]["id"]].append((nodes[i]["id"], round(s, 3)))
    return dict(out)


def tag_bridge_nodes(nodes: list, edges: list) -> None:
    """Mark nodes whose neighbors span 3+ distinct clusters as bridges (sets n['is_bridge'])."""
    nbr_clusters = defaultdict(set)
    by_id = {n["id"]: n for n in nodes}
    for e in edges:
        sn = by_id.get(e["source"])
        tn = by_id.get(e["target"])
        if not (sn and tn):
            continue
        nbr_clusters[e["source"]].add(tn["cluster"])
        nbr_clusters[e["target"]].add(sn["cluster"])
    for n in nodes:
        clusters_touched = nbr_clusters.get(n["id"], set())
        n["is_bridge"] = len(clusters_touched) >= 3


# -----------------------------------------------------------------------------
# Insights: stuck patterns, cluster digests, forgotten gold
# -----------------------------------------------------------------------------

def group_repeat_clusters(repeats: dict, nodes: list) -> list:
    """Union-find on repeat-question pairs. Returns groups of node IDs whose
    opening prompts are all mutually similar."""
    parent = {n["id"]: n["id"] for n in nodes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for nid, lst in repeats.items():
        for other_id, _sim in lst:
            if other_id in parent and nid in parent:
                union(nid, other_id)

    by_id = {n["id"]: n for n in nodes}
    groups = defaultdict(list)
    for n in nodes:
        if n["id"] in repeats and repeats[n["id"]]:
            groups[find(n["id"])].append(n["id"])

    out = []
    for ids in groups.values():
        if len(ids) < 2:
            continue
        members = sorted([by_id[i] for i in ids], key=lambda x: x.get("date") or "")
        out.append({
            "size": len(members),
            "first_date": members[0].get("date", ""),
            "last_date": members[-1].get("date", ""),
            "theme": members[0]["title"],  # approx — use earliest title as theme
            "members": [
                {"id": m["id"], "title": m["title"], "date": m["date"], "source": m["source"], "messages": m["messages"], "cluster": m["cluster"]}
                for m in members
            ],
        })
    out.sort(key=lambda g: g["size"], reverse=True)
    return out[:30]


def build_cluster_digests(nodes: list, clusters: list) -> dict:
    """For each cluster, compile metadata: count, date range, top chats by length."""
    by_cluster = defaultdict(list)
    for n in nodes:
        by_cluster[n["cluster"]].append(n)
    out = {}
    for c in clusters:
        members = by_cluster.get(c["id"], [])
        if not members:
            continue
        members_sorted = sorted(members, key=lambda x: x["messages"], reverse=True)
        dates = sorted([m.get("date") or "" for m in members if m.get("date")])
        out[c["id"]] = {
            "name": c["name"],
            "count": len(members),
            "date_range": [dates[0] if dates else "", dates[-1] if dates else ""],
            "total_messages": sum(m.get("messages", 0) for m in members),
            "top_chats": [
                {"id": m["id"], "title": m["title"], "messages": m["messages"], "date": m["date"]}
                for m in members_sorted[:6]
            ],
        }
    return out


def compute_forgotten_gold(nodes: list, today_iso: str = None) -> list:
    """Long, productive chats not touched recently. Score = messages * (days_ago/30)."""
    if today_iso is None:
        today_iso = datetime.now().isoformat()[:10]
    try:
        today = datetime.fromisoformat(today_iso)
    except Exception:
        today = datetime.now()
    out = []
    for n in nodes:
        try:
            last = datetime.fromisoformat((n.get("last_date") or n.get("date") or "1970-01-01"))
        except Exception:
            continue
        days_ago = (today - last).days
        if n.get("messages", 0) < 20 or days_ago < 30:
            continue
        score = n["messages"] * (days_ago / 30.0)
        out.append({
            "id": n["id"], "title": n["title"], "messages": n["messages"],
            "days_ago": days_ago, "date": n["date"], "source": n["source"],
            "cluster": n["cluster"], "score": round(score, 1),
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:15]


# -----------------------------------------------------------------------------
# Render
# -----------------------------------------------------------------------------

def render_html(graph: dict, template_path: Path) -> str:
    template = template_path.read_text(encoding="utf-8")
    stats = graph["stats"]
    sources = stats["by_source"]
    stats_text = f'{stats["nodes"]} conversations · {stats["edges"]} connections · ' + \
                 " · ".join(f"{n} {s}" for s, n in sources.items())
    source_chips = "".join(
        f'<button class="chip active" data-src="{s}">{s} <span class="count">{n}</span></button>'
        for s, n in sources.items()
    )
    used_clusters = {n["cluster"] for n in graph["nodes"]}
    legend_items = "".join(
        f'<div class="item" data-cluster="{c["id"]}"><span class="dot" style="background:{c["color"]};color:{c["color"]}"></span>{c["name"]}</div>'
        for c in graph["clusters"] if c["id"] in used_clusters
    )
    graph_json_str = json.dumps(graph, separators=(",", ":"))
    return (template
            .replace("__STATS__", stats_text)
            .replace("__SOURCE_CHIPS__", source_chips)
            .replace("__LEGEND__", legend_items)
            .replace("__GRAPH_JSON__", graph_json_str))


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Build a beautiful constellation map of all your Claude conversations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--code", default="~/.claude/projects",
                    help="Claude Code / Cowork session storage (default: %(default)s)")
    ap.add_argument("--web-export",
                    help="claude.ai data export — zip file or unzipped directory")
    ap.add_argument("--output", default="./conversation-constellation.html",
                    help="output HTML file (default: %(default)s)")
    ap.add_argument("--template", default=None,
                    help="HTML template (default: ./template.html alongside this script)")
    ap.add_argument("--min-messages", type=int, default=1,
                    help="drop arcs with fewer messages than this (default: %(default)s — set to 4+ to filter out short sessions)")
    ap.add_argument("--gap-hours", type=float, default=4.0,
                    help="split a session into arcs when user idle exceeds this (default: %(default)s)")
    ap.add_argument("--max-clusters", type=int, default=12,
                    help="cap the number of distinct clusters (default: %(default)s)")
    ap.add_argument("--knn", type=int, default=6,
                    help="how many similar neighbors to compute per node (default: %(default)s)")
    ap.add_argument("--max-bridges", type=int, default=35,
                    help="cap the number of cross-cluster semantic bridge edges (default: %(default)s)")
    ap.add_argument("--no-embeddings", action="store_true",
                    help="skip dense embeddings (always use TF-IDF)")
    ap.add_argument("--no-llm-names", action="store_true",
                    help="skip LLM cluster naming even if ANTHROPIC_API_KEY is set")
    ap.add_argument("--graph-json", default=None,
                    help="also write the raw graph JSON to this path")
    args = ap.parse_args()

    code_root = Path(os.path.expanduser(args.code))
    template_path = Path(args.template) if args.template else Path(__file__).parent / "template.html"
    output_path = Path(os.path.expanduser(args.output))

    if not template_path.exists():
        print(f"Error: template not found at {template_path}", file=sys.stderr)
        sys.exit(1)

    print(f"▸ Crawling local sessions at {code_root}")
    local = crawl_local(code_root, args.gap_hours)
    print(f"  found {len(local)} arc(s)")

    web = []
    if args.web_export:
        export_path = Path(os.path.expanduser(args.web_export))
        print(f"▸ Crawling claude.ai export at {export_path}")
        web = crawl_web_export(export_path)
        print(f"  found {len(web)} web conversations")

    nodes = local + web
    nodes = [n for n in nodes if n["messages"] >= args.min_messages]
    if not nodes:
        print("Error: no conversations found. Have you used Claude Code or provided --web-export?", file=sys.stderr)
        sys.exit(1)

    # Refine source attribution
    for n in nodes:
        n["source"] = attribute_source(n)

    print(f"▸ Computing semantic clusters")
    clusters, vectors, neighbors = assign_clusters(
        nodes,
        max_clusters=args.max_clusters,
        knn=args.knn,
        use_embeddings=not args.no_embeddings,
    )
    print(f"  {len(clusters)} cluster(s) (pre-naming): {[c['name'] for c in clusters]}")

    # LLM cluster naming via Claude Haiku (no-op if ANTHROPIC_API_KEY not set)
    if not args.no_llm_names and os.environ.get("ANTHROPIC_API_KEY"):
        print(f"▸ Asking Claude Haiku to name clusters")
        name_map = name_clusters_with_llm(clusters, nodes)
        renamed = 0
        for c in clusters:
            if c["id"] in name_map:
                c["name"] = name_map[c["id"]]
                renamed += 1
        print(f"  renamed {renamed}/{len(clusters)} clusters")
        print(f"  final names: {[c['name'] for c in clusters]}")
    elif not args.no_llm_names:
        print(f"  (skipping LLM cluster naming — set ANTHROPIC_API_KEY to enable)")

    print(f"▸ Building edges")
    edges = build_edges(nodes, neighbors=neighbors, max_semantic=args.max_bridges)
    print(f"  {len(edges)} edge(s)")

    print(f"▸ Detecting repeat questions and bridge nodes")
    repeats = detect_repeat_questions(nodes)
    tag_bridge_nodes(nodes, edges)
    n_repeat = sum(1 for ns in repeats.values() if ns)
    n_bridge = sum(1 for n in nodes if n.get("is_bridge"))
    print(f"  {n_repeat} chats with repeat-question siblings, {n_bridge} bridge nodes")

    print(f"▸ Computing insights (stuck patterns, cluster digests, forgotten gold)")
    repeat_clusters = group_repeat_clusters(repeats, nodes)
    cluster_digests = build_cluster_digests(nodes, clusters)
    forgotten_gold = compute_forgotten_gold(nodes)
    print(f"  {len(repeat_clusters)} repeat-pattern groups, {len(forgotten_gold)} forgotten-gold candidates")

    # Per-node TF-IDF retrieval vectors for the in-browser Q&A panel.
    # Always TF-IDF (the browser doesn't run embeddings). Top-30 terms only to
    # keep the inlined HTML payload reasonable.
    print(f"▸ Building Q&A retrieval index (TF-IDF, top-30 terms per chat)")
    qa_docs = []
    for n in nodes:
        parts = [
            (n.get("title", "") or "") + " " + (n.get("title", "") or ""),  # title 2x
            n.get("preview", "") or "",
            n.get("summary_seed", "") or "",
            " ".join(n.get("topics", []) or []),
        ]
        qa_docs.append(" ".join(p for p in parts if p))
    qa_vecs = tfidf_vectors(qa_docs)
    for i, n in enumerate(nodes):
        top = sorted(qa_vecs[i].items(), key=lambda x: -x[1])[:30]
        n["qa_vec"] = {t: round(w, 4) for t, w in top}

    # Build summaries
    for n in nodes:
        n["summary"] = short_summary(n.get("summary_seed", "") or n.get("preview", ""))

    graph = {
        "clusters": clusters,
        "nodes": [
            {
                "id": n["id"],
                "title": n["title"],
                "source": n["source"],
                "cluster": n["cluster"],
                "project": n.get("project", ""),
                "date": n["date"],
                "last_date": n.get("last_date", n["date"]),
                "messages": n["messages"],
                "topics": n["topics"][:5],
                "summary": n["summary"],
                "preview": n.get("preview", "")[:240],
                "is_bridge": bool(n.get("is_bridge")),
                "repeats": repeats.get(n["id"], [])[:5],
                "qa_vec": n.get("qa_vec", {}),
            }
            for n in nodes
        ],
        "edges": edges,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "by_source": dict(Counter(n["source"] for n in nodes)),
            "by_cluster": dict(Counter(n["cluster"] for n in nodes)),
            "bridge_count": n_bridge,
            "repeat_count": n_repeat,
            # If there are no Web-source chats, the user probably hasn't done
            # the claude.ai data export — the HTML viewer uses this flag to
            # show a first-run banner explaining how to get them.
            "needs_web_export": Counter(n["source"] for n in nodes).get("Web", 0) == 0,
        },
        "insights": {
            "repeat_clusters": repeat_clusters,
            "cluster_digests": cluster_digests,
            "forgotten_gold": forgotten_gold,
        },
    }

    if args.graph_json:
        graph_json_path = Path(os.path.expanduser(args.graph_json))
        graph_json_path.write_text(json.dumps(graph, indent=2))
        print(f"▸ Wrote graph JSON to {graph_json_path}")

    print(f"▸ Rendering HTML")
    html = render_html(graph, template_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"\n✓ Wrote {output_path}")
    print(f"  open it in a browser to explore your conversation constellation.")


if __name__ == "__main__":
    main()
