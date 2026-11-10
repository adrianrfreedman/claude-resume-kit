#!/usr/bin/env bash
# Render a resume/CL HTML file to PDF via headless Chrome and report the page count.
# Usage: bash render_pdf.sh path/to/file.html [output.pdf]
# ponytail: Chrome is already installed; no new dependency. Honors @media print + page-break CSS.
set -euo pipefail

html="${1:?usage: render_pdf.sh file.html [out.pdf]}"
pdf="${2:-${html%.html}.pdf}"

chrome="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$chrome" ] || chrome="$(command -v google-chrome || command -v chromium || true)"
[ -n "$chrome" ] || { echo "No Chrome/Chromium found" >&2; exit 1; }

abs="$(cd "$(dirname "$html")" && pwd)/$(basename "$html")"
"$chrome" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$pdf" "file://$abs" 2>/dev/null

# Page count: prefer pdfinfo, fall back to a grep of the PDF.
if command -v pdfinfo >/dev/null 2>&1; then
  pages="$(pdfinfo "$pdf" | awk '/^Pages:/{print $2}')"
else
  pages="$(grep -c '/Type\s*/Page[^s]' "$pdf" || echo '?')"
fi
echo "Wrote $pdf — $pages page(s). Now READ the PDF to verify layout and page fill."
