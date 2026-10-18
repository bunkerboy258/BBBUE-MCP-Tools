from collections import defaultdict

import numpy as np

from BBBGripGeometry import TriangleSurface


class WeldedSolidSurface:
    """/** 对焊接后的闭合连通面片执行独立多方向射线包含查询 */"""

    def __init__(self, triangles, weld_tolerance_cm=.00001):
        """/** @param triangles 同一空间实际三角面 @param weld_tolerance_cm 位置量化焊接容差 @return 连通组件和边拓扑 不假定开放网格是实体 */"""
        triangles = np.asarray(triangles, dtype=float)
        if triangles.ndim != 3 or triangles.shape[1:] != (3, 3) or not len(triangles) or not np.all(np.isfinite(triangles)):
            raise ValueError('实体审计需要非空有限三角面')
        if not np.isfinite(weld_tolerance_cm) or weld_tolerance_cm <= 0:
            raise ValueError('焊接容差必须为正有限数')
        self.tolerance = weld_tolerance_cm
        quantized = np.rint(triangles.reshape(-1, 3)/weld_tolerance_cm).astype(np.int64)
        _, inverse = np.unique(quantized, axis=0, return_inverse=True)
        welded = inverse.reshape(-1, 3)
        self.parents = list(range(len(triangles)))
        edge_faces = defaultdict(list)
        degenerate = 0
        valid_faces = []
        for index, corners in enumerate(welded):
            if len(set(corners)) != 3 or np.linalg.norm(np.cross(triangles[index, 1]-triangles[index, 0], triangles[index, 2]-triangles[index, 0])) <= 1e-12:
                degenerate += 1
                continue
            valid_faces.append(index)
            for a, b in zip(corners, np.roll(corners, -1)):
                key = (min(int(a), int(b)), max(int(a), int(b)))
                direction = int(a) < int(b)
                edge_faces[key].append((index, direction))
        for incident in edge_faces.values():
            for item in incident[1:]:
                self._union(incident[0][0], item[0])
        grouped = defaultdict(list)
        for index in valid_faces:
            grouped[self._find(index)].append(index)
        grouped_edges = defaultdict(list)
        for incidents in edge_faces.values():
            grouped_edges[self._find(incidents[0][0])].append(incidents)
        self.components = []
        for component, (identifier, faces) in enumerate(grouped.items()):
            edges = grouped_edges[identifier]
            boundary = sum(len(incident) == 1 for incident in edges)
            non_manifold = sum(len(incident) > 2 for incident in edges)
            orientation_errors = sum(len(incident) == 2 and incident[0][1] == incident[1][1] for incident in edges)
            mesh = triangles[faces]
            closed = boundary == 0 and non_manifold == 0
            report = {'component': component, 'triangles': len(faces), 'boundaryEdges': boundary,
                      'nonManifoldEdges': non_manifold, 'orientationMismatches': orientation_errors,
                      'status': 'closed_2_manifold' if closed else 'inconclusive_open_or_non_manifold',
                      'orientationConsistent': orientation_errors == 0}
            self.components.append((report, mesh))
        self.degenerate_count = degenerate
        self.depth_queries = {}

    def _depth_query(self, component, triangles):
        if component not in self.depth_queries:
            vertices = [{'id': index, 'position': point.tolist()} for index, point in enumerate(triangles.reshape(-1, 3))]
            faces = [{'id': index, 'vertices': [index*3, index*3+1, index*3+2]} for index in range(len(triangles))]
            self.depth_queries[component] = TriangleSurface({'vertices': vertices, 'triangles': faces})
        return self.depth_queries[component]

    def _find(self, index):
        while self.parents[index] != index:
            self.parents[index] = self.parents[self.parents[index]]
            index = self.parents[index]
        return index

    def _union(self, first, second):
        first = self._find(first)
        second = self._find(second)
        if first != second:
            self.parents[second] = first

    def _classify(self, points, triangles):
        minimum = triangles.min(axis=(0, 1))-self.tolerance
        maximum = triangles.max(axis=(0, 1))+self.tolerance
        relevant = np.where(np.all((points >= minimum) & (points <= maximum), axis=1))[0]
        result = np.zeros(len(points), dtype=int)
        a = triangles[:, 0]
        edge1 = triangles[:, 1]-a
        edge2 = triangles[:, 2]-a
        for start in range(0, len(relevant), 64):
            rows = relevant[start:start+64]
            queries = points[rows]
            votes = []
            for direction in ([1, .19371, .31791], [.27183, 1, .41973], [.34719, .23149, 1]):
                direction = np.asarray(direction, dtype=float)
                direction /= np.linalg.norm(direction)
                h = np.cross(direction, edge2)
                determinant = np.einsum('ij,ij->i', edge1, h)
                valid = np.abs(determinant) > 1e-12
                inverse = np.zeros_like(determinant)
                inverse[valid] = 1/determinant[valid]
                delta = queries[:, None, :]-a
                u = np.sum(delta*h, axis=2)*inverse
                q = np.cross(delta, edge1)
                v = np.sum(q*direction, axis=2)*inverse
                t = np.sum(q*edge2, axis=2)*inverse
                on_face = valid & (u >= -1e-9) & (v >= -1e-9) & (u+v <= 1+1e-9)
                boundary = np.any(on_face & (np.abs(t) <= self.tolerance), axis=1)
                hit = on_face & (t > self.tolerance)
                edge_hit = hit & ((u < 1e-8) | (v < 1e-8) | (1-u-v < 1e-8))
                code = np.sum(hit, axis=1) % 2
                code[np.any(edge_hit, axis=1)] = -1
                code[boundary] = 2
                votes.append(code)
            votes = np.asarray(votes)
            for column, row in enumerate(rows):
                values = votes[:, column]
                if np.any(values == 2):
                    result[row] = 2
                    continue
                valid = values[values >= 0]
                result[row] = -1
                if len(valid) >= 2 and np.all(valid == valid[0]):
                    result[row] = int(valid[0])
        return result

    def audit(self, points, vertex_ids=None):
        """/** @param points 手部实际表面点 @param vertex_ids 原始顶点编号 @return 各闭合组件的包含结果 开口覆盖与实体解释限制 */"""
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3 or not np.all(np.isfinite(points)):
            raise ValueError('实体审计点必须为有限三维数组')
        if vertex_ids is None:
            vertex_ids = list(range(len(points)))
        if len(vertex_ids) != len(points):
            raise ValueError('实体审计编号数量不匹配')
        inside = np.zeros(len(points), dtype=bool)
        boundary = np.zeros(len(points), dtype=bool)
        ambiguous = np.zeros(len(points), dtype=bool)
        maximum_depth = np.zeros(len(points))
        reports = []
        closed_count = 0
        for source, triangles in self.components:
            report = dict(source)
            if source['status'] == 'closed_2_manifold':
                closed_count += 1
                classified = self._classify(points, triangles)
                inside |= classified == 1
                boundary |= classified == 2
                ambiguous |= classified == -1
                report['insideCount'] = int((classified == 1).sum())
                report['boundaryCount'] = int((classified == 2).sum())
                report['rayInconclusiveCount'] = int((classified == -1).sum())
                report['insideVertexIds'] = [int(vertex_ids[index]) for index in np.where(classified == 1)[0][:32]]
                inside_rows = np.where(classified == 1)[0]
                depths = np.empty(0)
                if len(inside_rows):
                    query = self._depth_query(source['component'], triangles)
                    depths = np.asarray([query.nearest(points[index])['distanceCm'] for index in inside_rows])
                    maximum_depth[inside_rows] = np.maximum(maximum_depth[inside_rows], depths)
                report['insideDepthMaximumCm'] = float(depths.max()) if len(depths) else 0.0
                report['insideDepthP95Cm'] = float(np.percentile(depths, 95)) if len(depths) else 0.0
            reports.append(report)
        coverage_complete = closed_count == len(self.components) and closed_count > 0 and self.degenerate_count == 0
        return {'weldToleranceCm': self.tolerance, 'components': reports,
                'closedComponentCount': closed_count, 'openOrNonManifoldComponentCount': len(self.components)-closed_count,
                'degenerateTriangleCount': self.degenerate_count, 'insideClosedComponentPointCount': int(inside.sum()),
                'insideClosedComponentVertexIds': [int(vertex_ids[index]) for index in np.where(inside)[0][:64]],
                'surfaceBoundaryPointCount': int(boundary.sum()), 'rayInconclusivePointCount': int(ambiguous.sum()),
                'insideDepthMaximumCm': float(maximum_depth.max()) if len(maximum_depth) else 0.0,
                'insideDepthP95Cm': float(np.percentile(maximum_depth[inside], 95)) if np.any(inside) else 0.0,
                'deepestPoints': [{'id': int(vertex_ids[index]), 'depthCm': float(maximum_depth[index])}
                                  for index in np.argsort(maximum_depth)[::-1][:16] if maximum_depth[index] > 0],
                'wholeSurfaceCoverage': 'closed_components_only' if coverage_complete else 'inconclusive_open_non_manifold_or_degenerate_components',
                'wholeWeaponSolidPenetrationProven': False, 'selfIntersectionTested': False,
                'assumption': 'component_containment_requires_non_self_intersecting_closed_shell_no_csg_or_cavity_inference'}
