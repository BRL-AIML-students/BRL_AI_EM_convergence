"""Internal CLI process protocol; native CAD output is captured by the parent."""
import json
import sys

from .__main__ import PROTOCOL, execute

if __name__ == '__main__':
    code, state = execute(sys.argv[1])
    print(PROTOCOL + json.dumps(state, ensure_ascii=False), flush=True)
    raise SystemExit(code)
