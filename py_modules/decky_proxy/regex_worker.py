"""Private, isolated evaluator: only bounded membership bitsets leave the child."""

import json
import re
import resource
import sys

MAX_SOURCE_BYTES = 16 * 1024


def _text(value: object, maximum: int, *, allow_empty: bool = False) -> bool:
    return (isinstance(value, str) and (allow_empty or bool(value))
            and len(value.encode("utf-8")) <= maximum
            and not re.search(r"[\x00-\x1f\x7f]", value))


def main() -> int:
    """Return only bitsets: 2 invalid input, 3 invalid syntax, 4 resource failure."""
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
        if (not isinstance(patterns, list) or len(patterns) > 512
                or not isinstance(names, list) or len(names) > 2304
                or any(not _text(pattern, MAX_SOURCE_BYTES, allow_empty=True)
                       for pattern in patterns)
                or any(not _text(name, 512) or len(name) > 128 for name in names)):
            return 2
        output = []
        for pattern in patterns:
            compiled = tuple(re.compile(part) for part in pattern.split("`"))
            output.append("".join("1" if any(part.search(name) for part in compiled) else "0"
                                  for name in names))
        sys.stdout.write(json.dumps(output, separators=(",", ":")))
        return 0
    except (re.error, RecursionError, OverflowError):
        return 3
    except (OSError, MemoryError):
        return 4
    except (KeyError, TypeError, ValueError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
