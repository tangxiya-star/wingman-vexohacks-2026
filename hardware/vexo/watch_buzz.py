"""Send one local command to an already connected Vexo Watch app; no retries."""

import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from watch_haptics import KINDS, RUNTIME


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=tuple(KINDS), default="notification")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    try:
        token = (RUNTIME / "watch_haptics.token").read_text().strip()
        request = Request(f"http://127.0.0.1:{args.port}/buzz",
            data=json.dumps({"kind": args.kind}).encode(),
            headers={"Content-Type": "application/json", "X-Vexo-Token": token}, method="POST")
        with urlopen(request, timeout=7) as response:
            print(response.read().decode())
    except HTTPError as error:
        print(error.read().decode())
        return 1
    except (OSError, URLError) as error:
        print(f"未确认执行：{error}；不会重试。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
