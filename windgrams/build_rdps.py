"""Entry point: builds windgram profiles from the latest RDPS 10 km run."""

from .build import run
from .geomet import RDPS

if __name__ == "__main__":
    run(RDPS)
