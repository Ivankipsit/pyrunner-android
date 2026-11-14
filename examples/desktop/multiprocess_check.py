"""Desktop only. Android cannot spawn real processes from a script.

Run this on Windows (or the Linux dev host). It uses the spawn start method,
which is what Windows uses, so a success here is the same path as the PC app.
"""

import multiprocessing as mp


def square(n: int) -> int:
    return n * n


def main() -> None:
    ctx = mp.get_context("spawn")
    with ctx.Pool(2) as pool:
        print(pool.map(square, [2, 3, 4, 5]), flush=True)


if __name__ == "__main__":
    main()
