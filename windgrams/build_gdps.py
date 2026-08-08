"""Entry point: builds windgram profiles from the latest GDPS 15 km run."""

from .build import run
from .geomet import GDPS

if __name__ == "__main__":
    run(GDPS)
