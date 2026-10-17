"""Private, isolated evaluator: only bounded membership bitsets leave the child."""

import json
import re
import resource
import sys


def main() -> int:
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
        # Darwin rejects both RLIMIT_AS and RLIMIT_DATA. The target SteamOS
        # runtime requires the address-space bound; macOS is development only.
        if sys.platform != "darwin":
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        payload = sys.stdin.buffer.read(8 * 1024 * 1024 + 1)
        if len(payload) > 8 * 1024 * 1024:
            return 2
        data = json.loads(payload)
        patterns, names = data["patterns"], data["names"]
        if len(patterns) > 512 or len(names) > 2304:
            return 2
        output = []
        for pattern in patterns:
            compiled = tuple(re.compile(part) for part in pattern.split("`"))
            output.append("".join("1" if any(part.search(name) for part in compiled) else "0"
                                  for name in names))
        sys.stdout.write(json.dumps(output, separators=(",", ":")))
        return 0
    except (KeyError, TypeError, ValueError, OSError, MemoryError, re.error):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
