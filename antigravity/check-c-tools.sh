#!/bin/bash
set -euo pipefail
for command in gcc g++ make cmake ninja pkg-config gdb clangd clang-format clang-tidy cppcheck; do
    command -v "$command" >/dev/null || { echo "Missing development tool: $command" >&2; exit 1; }
done
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
cat > "$stage/check.c" <<'C'
#include <stdio.h>
int main(void) { puts("C_OK"); return 0; }
C
cat > "$stage/check.cpp" <<'CPP'
#include <iostream>
#include <numeric>
#include <vector>
int main() {
    const std::vector<int> values{1, 2, 3};
    if (std::accumulate(values.begin(), values.end(), 0) != 6) return 1;
    std::cout << "CPP_OK\n";
}
CPP
gcc -std=c11 -Wall -Wextra -Werror "$stage/check.c" -o "$stage/check-c"
g++ -std=c++17 -Wall -Wextra -Werror "$stage/check.cpp" -o "$stage/check-cpp"
test "$("$stage/check-c")" = C_OK
test "$("$stage/check-cpp")" = CPP_OK
echo 'C/C++ compilation and execution passed; development tools are present.'
