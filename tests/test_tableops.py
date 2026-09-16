"""python tests/test_tableops.py -- plain asserts, no pytest needed."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import numpy as np
from tuner.core import tableops as ops
from tuner.core.table import Table

v = np.zeros((4, 5))
v[0, 0], v[0, 4], v[3, 0], v[3, 4] = 1.0, 2.0, 3.0, 4.0
ops.interpolate(v, 0, 3, 0, 4)
assert abs(v[0, 2] - 1.5) < 1e-9, "top row midpoint"
assert abs(v[3, 2] - 3.5) < 1e-9, "bottom row midpoint"
assert abs(v[1, 0] - (1 + 2 / 3)) < 1e-9, "left column third"
assert abs(v[1, 2] - (1.5 + (3.5 - 1.5) / 3)) < 1e-9, "interior bilinear"
print("interpolate      ok")

v = np.ones((3, 3)); v[1, 1] = 10.0
m = np.zeros_like(v, bool); m[1, 1] = True
ops.smooth(v, m)
assert abs(v[1, 1] - (8 + 10) / 9) < 1e-9 and v[0, 0] == 1.0, "3x3 mean, only selected cell"
print("smooth           ok")

v = np.full((2, 2), 2.0); m = np.array([[True, False], [False, True]])
ops.bump(v, m, 0.5); ops.scale(v, m, 2.0)
assert v.tolist() == [[5.0, 2.0], [2.0, 5.0]]
ops.set_value(v, m, 7.0); assert v[0, 0] == 7.0 and v[0, 1] == 2.0
print("bump/scale/set   ok")

v = np.arange(6, dtype=float).reshape(2, 3)
t = ops.to_tsv(v, 0, 1, 0, 2, "{:.0f}")
assert t == "3\t4\t5\n0\t1\t2", "display order: high j first"
back = ops.from_tsv(t)
assert back.tolist() == [[3, 4, 5], [0, 1, 2]]
assert ops.from_tsv("1\t2\n3") is None, "ragged rejected"
assert ops.from_tsv("1, 2\n3, 4").tolist() == [[1, 2], [3, 4]], "commas accepted"
print("tsv round trip   ok")

tb = Table("t", "T", "x", "", "y", "", [0, 10], [0, 10], [[0, 10], [10, 20]])
out = ops.regrid(tb.values, tb.x, tb.y, np.array([0, 5, 10.0]), np.array([0, 5, 10.0]), tb.lookup)
assert out[1, 1] == 10.0 and out[0, 1] == 5.0 and out[2, 2] == 20.0, "regrid samples the surface"
print("regrid           ok")
print("all table ops pass")
