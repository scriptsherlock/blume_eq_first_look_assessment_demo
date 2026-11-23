"""Evidence Map server."""
import os

# NumPy's maths library reserves memory per CPU core at import. On a busy Windows machine
# that reservation can fail ("OpenBLAS: memory allocation failed"). One thread is plenty here.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
