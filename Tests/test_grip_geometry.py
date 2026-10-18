import math
from pathlib import Path
import random
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from BBBGripGeometry import TriangleSurface, audit_contacts, closest_point_triangle


class GripGeometryTests(unittest.TestCase):
    def assert_point(self, actual, expected):
        for value, target in zip(actual, expected):
            self.assertAlmostEqual(value, target, places=10)

    def test_triangle_face_edge_and_corner(self):
        triangle = ((0, 0, 0), (2, 0, 0), (0, 2, 0))
        self.assert_point(closest_point_triangle((0.4, 0.6, 3), *triangle), (0.4, 0.6, 0))
        self.assert_point(closest_point_triangle((2, 2, 1), *triangle), (1, 1, 0))
        self.assert_point(closest_point_triangle((-2, -2, 1), *triangle), (0, 0, 0))

    def test_degenerate_triangle_and_point(self):
        self.assert_point(closest_point_triangle((1, 2, 3), (0, 0, 0), (2, 0, 0), (2, 0, 0)), (1, 0, 0))
        self.assert_point(closest_point_triangle((1, 2, 3), (4, 5, 6), (4, 5, 6), (4, 5, 6)), (4, 5, 6))

    def test_sparse_ids_and_explicit_region(self):
        surface = {"vertices": [{"id": identifier, "position": position} for identifier, position in
            [(10, (0, 0, 0)), (20, (2, 0, 0)), (30, (0, 2, 0)), (70, (0, 0, 10)), (80, (2, 0, 10)), (90, (0, 2, 10))]],
            "triangles": [{"id": 100, "vertices": [10, 20, 30]}, {"id": 200, "vertices": [70, 80, 90]}]}
        unrestricted = TriangleSurface(surface).nearest((0.5, 0.5, 9))
        restricted = TriangleSurface(surface, [100]).nearest((0.5, 0.5, 9))
        self.assertEqual(unrestricted["triangle"], 200)
        self.assertAlmostEqual(unrestricted["distanceCm"], 1)
        self.assertAlmostEqual(restricted["distanceCm"], 9)
        self.assertAlmostEqual(unrestricted["normalGapCm"], -1)
        self.assertAlmostEqual(restricted["normalGapCm"], 9)

    def test_tree_matches_exhaustive_search(self):
        generator = random.Random(7913)
        points = [(generator.uniform(-20, 20), generator.uniform(-20, 20), generator.uniform(-20, 20)) for index in range(240)]
        surface = {"vertices": [{"id": index, "position": point} for index, point in enumerate(points)],
            "triangles": [{"id": index // 3, "vertices": [index, index + 1, index + 2]} for index in range(0, len(points), 3)]}
        tree = TriangleSurface(surface)
        for query in [(generator.uniform(-40, 40), generator.uniform(-40, 40), generator.uniform(-40, 40)) for index in range(40)]:
            expected = min(math.dist(query, closest_point_triangle(query, *points[index:index + 3])) for index in range(0, len(points), 3))
            self.assertAlmostEqual(tree.nearest(query)["distanceCm"], expected, places=10)

    def test_contact_sign_does_not_claim_volume_penetration(self):
        surface = {"vertices": [{"id": 0, "position": (0, 0, 0)}, {"id": 1, "position": (2, 0, 0)}, {"id": 2, "position": (0, 2, 0)}],
            "triangles": [{"id": 8, "vertices": [0, 1, 2]}]}
        result = audit_contacts([{"id": "pad", "position": (0.3, 0.3, -0.1)}], surface)
        self.assertFalse(result["summary"]["normalSignIsVolumeClassification"])
        self.assertAlmostEqual(result["points"][0]["normalGapCm"], -0.1)
        self.assertAlmostEqual(result["summary"]["maximumCm"], 0.1)

    def test_invalid_geometry_fails_explicitly(self):
        with self.assertRaises(ValueError):
            TriangleSurface({"vertices": [], "triangles": []})

        with self.assertRaises(ValueError):
            TriangleSurface({"vertices": [{"id": 0, "position": (math.inf, 0, 0)}], "triangles": [{"id": 0, "vertices": [0, 0, 0]}]})


if __name__ == "__main__":
    unittest.main()
