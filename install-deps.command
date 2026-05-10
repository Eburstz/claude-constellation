#!/bin/bash
# Installs the optional Python deps that unlock the better features:
#   - fastembed → real semantic clustering via local embeddings (~200MB)
# (Already-set ANTHROPIC_API_KEY enables LLM cluster naming via Claude Haiku.)

set -e

echo ""
echo "╭───────────────────────────────────────────────╮"
echo "│   claude-constellation — install deps         │"
echo "╰───────────────────────────────────────────────╯"
echo ""

# Try pip first, fall back to pip3
PIP_BIN=""
if command -v pip3 >/dev/null 2>&1; then PIP_BIN="pip3"
elif command -v pip >/dev/null 2>&1; then PIP_BIN="pip"
else
  echo "✗ pip not found. Install Python 3 first (e.g. brew install python)."
  read -p "Press enter to close…"
  exit 1
fi

echo "▸ Using $PIP_BIN ($($PIP_BIN --version))"
echo ""
echo "▸ Installing fastembed (semantic embeddings)…"
echo "  This is ~200MB. First import downloads the bge-small-en-v1.5 model (~130MB)."
echo ""

$PIP_BIN install --user fastembed 2>&1 | tail -3 || \
  $PIP_BIN install --break-system-packages fastembed 2>&1 | tail -3 || true

echo ""
echo "▸ Verifying…"
python3 -c "
from fastembed import TextEmbedding
em = TextEmbedding('BAAI/bge-small-en-v1.5')
v = list(em.embed(['hello world']))
print(f'  ✓ fastembed working — {len(v[0])} dims per embedding')
" 2>&1 | tail -10

echo ""
echo "─────────────────────────────────────────────────"
echo "Optional: enable LLM-named clusters"
echo "─────────────────────────────────────────────────"
echo ""
echo "Add this line to your shell rc (~/.zshrc or ~/.bash_profile):"
echo ""
echo "    export ANTHROPIC_API_KEY=sk-ant-...your-key..."
echo ""
echo "Get a key at https://console.anthropic.com/. Cluster names become"
echo "concise human-readable labels via Claude Haiku (~12 calls per refresh,"
echo "results cached so refreshes are free)."
echo ""
read -p "Press enter to close…"
