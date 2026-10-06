#!/bin/bash
set -euo pipefail
pdf_test_dir=$(mktemp -d)
trap 'rm -rf "$pdf_test_dir"' EXIT
cat > "$pdf_test_dir/sample.md" <<'EOF'
# PDF generation check

A paragraph with **bold text**, accented text: café, and math: $x^2$.

| Item | Value |
|------|-------|
| Test | 42    |

```c
int main(void) { return 0; }
```
EOF
pandoc "$pdf_test_dir/sample.md" -o "$pdf_test_dir/sample.pdf"
python3 - "$pdf_test_dir/sample.pdf" <<'CHECK'
import sys
from pathlib import Path
assert Path(sys.argv[1]).read_bytes().startswith(b'%PDF-')
CHECK
