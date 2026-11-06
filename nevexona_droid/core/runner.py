"""Безопасный запуск внешних команд: только список аргументов, без shell."""
import subprocess
from dataclasses import dataclass


@dataclass
class Result:
    ok: bool
    code: int
    out: str
    err: str
    found: bool = True


def run(args, timeout=30):
    if not isinstance(args, (list, tuple)) or not all(isinstance(a, str) for a in args):
        raise TypeError("args must be a list of strings")
    try:
        p = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return Result(False, 127, "", f"{args[0]}: command not found", found=False)
    except subprocess.TimeoutExpired:
        return Result(False, 124, "", f"timeout after {timeout}s")
    return Result(p.returncode == 0, p.returncode, p.stdout, p.stderr)
