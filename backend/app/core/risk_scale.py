"""Bounds of the configurable risk matrix — the one place the ceiling is written down.

Four layers have to agree on how wide a likelihood x impact scale may be: the ORM check
constraints, the idempotent DDL patches, the Pydantic validators, and the scoring
functions. When they disagree the failure is quiet and nasty — the API accepts a score
the database then rejects, or worse, the reverse.

They cannot all import it from any one of themselves: the models would have to import a
service, the service imports the models' enums, and the cycle only shows up on whichever
entry point happens to import the DDL patches first. So the constants live here, in a
module that imports nothing at all.
"""
from __future__ import annotations

#: Below 3 the four severity bands collapse into each other.
MIN_MATRIX_SIZE = 3

#: The widest scale a tenant may configure. 10 because banks arrive with a
#: board-approved ERM matrix already in force and 1-10 is common; past that a
#: qualitative rung stops meaning anything an assessor can apply repeatably.
MAX_MATRIX_SIZE = 10

#: What a tenant gets until it says otherwise. Changing this would re-band every
#: unconfigured installation's register, so it does not change.
DEFAULT_MATRIX_SIZE = 5
