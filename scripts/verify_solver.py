"""Prove the container really has a working LP **and** MILP solver.

Run at image build time. SciPy wheels normally bundle HiGHS, but a stripped or mismatched build
can import cleanly and then fail the first time it is asked to solve something — which would
turn every judged request into a 500. Better to fail the build.

    python scripts/verify_solver.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running a script by path puts *its own* directory on sys.path, not the working directory, so
# `import app` would fail here and inside the image. Add the project root explicitly.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    import numpy as np
    import scipy
    from scipy.optimize import Bounds, LinearConstraint, linprog, milp

    print(f"numpy {np.__version__}, scipy {scipy.__version__}")

    # minimize x + 2y  subject to  x + y == 1,  0 <= x,y <= 1   ->  x=1, y=0, cost 1
    objective = np.array([1.0, 2.0])
    a_eq = np.array([[1.0, 1.0]])
    b_eq = np.array([1.0])

    lp = linprog(objective, A_eq=a_eq, b_eq=b_eq, bounds=[(0, 1), (0, 1)], method="highs")
    if not lp.success or abs(lp.fun - 1.0) > 1e-9:
        print(f"LP FAILED: success={lp.success} fun={getattr(lp, 'fun', None)}", file=sys.stderr)
        return 1
    print(f"LP ok (HiGHS): objective {lp.fun}")

    # Same problem with an integrality requirement, to exercise the branch-and-bound path.
    result = milp(
        objective,
        integrality=np.array([1, 1]),
        bounds=Bounds(np.array([0.0, 0.0]), np.array([1.0, 1.0])),
        constraints=[LinearConstraint(a_eq, b_eq, b_eq)],
    )
    if not result.success or abs(result.fun - 1.0) > 1e-9:
        print(f"MILP FAILED: success={result.success} fun={getattr(result, 'fun', None)}", file=sys.stderr)
        return 1
    print(f"MILP ok (HiGHS): objective {result.fun}")

    # The application itself must import: a missing module here is a broken image, not a
    # runtime surprise on the first judged request.
    from app.main import create_app

    create_app()
    print("application imports and builds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
