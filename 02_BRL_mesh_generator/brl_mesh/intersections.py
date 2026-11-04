"""Triangle interior intersections, independently of CAD or surface separation intent.

The BVH only supplies candidates. Predicates use a pair-local origin and scale;
positive separating distances are never rounded to zero to close an intended gap.
This is a floating-point audit, not an exact-arithmetic geometric certificate.
"""
from __future__ import annotations

import numpy as np

from .validation import Issue


class _TriangleBoxes:
    def __init__(self, triangles):
        self.low = triangles.min(axis=1)
        self.high = triangles.max(axis=1)
        self.nodes = []
        self.root = self._build(np.arange(len(triangles)))

    def _build(self, ids):
        lo, hi = self.low[ids].min(axis=0), self.high[ids].max(axis=0)
        index = len(self.nodes)
        self.nodes.append(None)
        if len(ids) <= 32:
            self.nodes[index] = (lo, hi, ids, -1, -1)
        else:
            centers = self.low[ids] / 2 + self.high[ids] / 2
            axis = np.argmax(np.ptp(centers, axis=0))
            ordered = ids[np.argsort(centers[:, axis], kind='stable')]
            middle = len(ids) // 2
            left, right = self._build(ordered[:middle]), self._build(ordered[middle:])
            self.nodes[index] = (lo, hi, None, left, right)
        return index

    def pairs(self):
        """Visit each overlapping unordered leaf pair once; no N x N allocation."""
        pending = [(self.root, self.root)]
        while pending:
            a, b = pending.pop()
            alo, ahi, ai, al, ar = self.nodes[a]
            blo, bhi, bi, bl, br = self.nodes[b]
            if np.any(alo > bhi) or np.any(blo > ahi):
                continue
            if ai is not None and bi is not None:
                mask = np.all(self.low[ai, None] <= self.high[bi], axis=2)
                mask &= np.all(self.low[bi] <= self.high[ai, None], axis=2)
                # Distinct leaves are visited only once by the tree traversal;
                # element IDs may occur in either order in those two leaves.
                # Only a self-leaf needs the strict index ordering mask.
                if a == b:
                    mask &= ai[:, None] < bi
                rows, cols = np.nonzero(mask)
                if len(rows):
                    yield ai[rows], bi[cols]
            elif a == b:
                pending.extend(((al, al), (al, ar), (ar, ar)))
            elif ai is None and (bi is not None or np.max(ahi-alo) >= np.max(bhi-blo)):
                pending.extend(((al, b), (ar, b)))
            else:
                pending.extend(((a, bl), (a, br)))


def _slice(triangle, distances, direction, tolerance):
    values = list(triangle[distances == 0] @ direction)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        if distances[i] * distances[j] < 0:
            fraction = distances[i] / (distances[i] - distances[j])
            values.append((triangle[i] + fraction*(triangle[j]-triangle[i])) @ direction)
    return min(values), max(values)


def _coplanar(a, b, normal, shared, tolerance):
    # SAT in the dominant 2D projection: positive area iff every interval
    # overlaps with positive depth. Boundary-only contacts remain the existing
    # node/edge auditor's responsibility.
    axis = int(np.argmax(np.abs(normal)))
    a, b = np.delete(a, axis, axis=1), np.delete(b, axis, axis=1)
    minimum = np.inf
    for triangle in (a, b):
        for i, j in ((0, 1), (1, 2), (2, 0)):
            edge = triangle[j] - triangle[i]
            perpendicular = np.array([-edge[1], edge[0]])
            length = np.linalg.norm(perpendicular)
            if length == 0:
                return 'uncertain_triangle_intersection'
            pa, pb = a @ perpendicular / length, b @ perpendicular / length
            depth = min(pa.max(), pb.max()) - max(pa.min(), pb.min())
            if depth < 0:
                return None
            minimum = min(minimum, depth)
    if minimum > tolerance:
        return 'triangle_intersection'
    if minimum == 0 or shared:
        return None
    return 'uncertain_triangle_intersection'


def _pair(a, b, shared):
    # Extended precision where provided by NumPy; even where longdouble equals
    # double, normalization avoids dependence on distant mesh components.
    a, b = a.astype(np.longdouble), b.astype(np.longdouble)
    origin = a[0].copy()
    a, b = a-origin, b-origin
    scale = max(np.max(np.abs(a)), np.max(np.abs(b)))
    if not np.isfinite(scale) or scale == 0:
        return 'uncertain_triangle_intersection'
    a, b = a/scale, b/scale
    na = np.cross(a[1]-a[0], a[2]-a[0])
    nb = np.cross(b[1]-b[0], b[2]-b[0])
    la, lb = np.linalg.norm(na), np.linalg.norm(nb)
    if la == 0 or lb == 0:
        return 'uncertain_triangle_intersection'
    na, nb = na/la, nb/lb
    da, db = (a-b[0]) @ nb, (b-a[0]) @ na
    equal = np.all(a[:, None, :] == b[None, :, :], axis=2)
    da[np.any(equal, axis=1)] = 0
    db[np.any(equal, axis=0)] = 0
    # A strictly positive gap, however small, is not a contact tolerance.
    ea = 32*np.finfo(float).eps*np.sum(np.abs((a-b[0])*nb), axis=1)
    eb = 32*np.finfo(float).eps*np.sum(np.abs((b-a[0])*na), axis=1)
    if np.all(da > ea) or np.all(da < -ea) or np.all(db > eb) or np.all(db < -eb):
        return None
    tolerance = 128 * np.finfo(np.longdouble).eps
    direction = np.cross(na, nb)
    length = np.linalg.norm(direction)
    if length <= tolerance:
        if max(np.max(np.abs(da)), np.max(np.abs(db))) > tolerance:
            return 'uncertain_triangle_intersection'
        return _coplanar(a, b, na, shared, tolerance)
    # Two distinct planes containing a shared edge meet only on that edge.
    if shared >= 2:
        return None
    direction /= length
    amin, amax = _slice(a, da, direction, tolerance)
    bmin, bmax = _slice(b, db, direction, tolerance)
    overlap = min(amax, bmax) - max(amin, bmin)
    # An isolated contact between independent triangles is nonconforming too:
    # no shared vertex authorizes the point, and node/edge auditing cannot
    # detect a vertex lying strictly inside another face. Negative overlap
    # remains a positive gap and must not be snapped into contact.
    if overlap > tolerance or (overlap == 0 and not shared):
        return 'triangle_intersection'
    if overlap <= 0 or shared:
        return None
    return 'uncertain_triangle_intersection'


def _batch(a, b, shared):
    """Vectorized equivalent of the local scalar predicate (0/blocked/incomplete)."""
    a, b = a.astype(np.longdouble), b.astype(np.longdouble)
    origin = a[:, :1].copy()
    a, b = a-origin, b-origin
    scale = np.maximum(np.max(np.abs(a), axis=(1, 2)), np.max(np.abs(b), axis=(1, 2)))
    invalid = ~np.isfinite(scale) | (scale == 0)
    scale[invalid] = 1
    a, b = a/scale[:, None, None], b/scale[:, None, None]
    na = np.cross(a[:, 1]-a[:, 0], a[:, 2]-a[:, 0])
    nb = np.cross(b[:, 1]-b[:, 0], b[:, 2]-b[:, 0])
    la, lb = np.linalg.norm(na, axis=1), np.linalg.norm(nb, axis=1)
    invalid |= (la == 0) | (lb == 0)
    na /= np.where(la == 0, 1, la)[:, None]
    nb /= np.where(lb == 0, 1, lb)[:, None]
    da = np.einsum('ijk,ik->ij', a-b[:, :1], nb)
    db = np.einsum('ijk,ik->ij', b-a[:, :1], na)
    equal = np.all(a[:, :, None, :] == b[:, None, :, :], axis=3)
    da[np.any(equal, axis=2)] = 0
    db[np.any(equal, axis=1)] = 0
    ea = 32*np.finfo(float).eps*np.sum(np.abs((a-b[:, :1])*nb[:, None]), axis=2)
    eb = 32*np.finfo(float).eps*np.sum(np.abs((b-a[:, :1])*na[:, None]), axis=2)
    separate = (np.all(da > ea, axis=1) | np.all(da < -ea, axis=1)
                | np.all(db > eb, axis=1) | np.all(db < -eb, axis=1))
    result = np.zeros(len(a), dtype=np.int8)
    result[invalid] = 2
    active = ~invalid & ~separate
    direction = np.cross(na, nb)
    length = np.linalg.norm(direction, axis=1)
    tolerance = 128 * np.finfo(np.longdouble).eps
    coplanar = active & (length <= tolerance)
    indices = np.flatnonzero(coplanar)
    if len(indices):
        ca, cb = a[indices], b[indices]
        drop = np.argmax(np.abs(na[indices]), axis=1)
        keep = np.array([[1, 2], [0, 2], [0, 1]])[drop]
        ca = np.take_along_axis(ca, keep[:, None, :], axis=2)
        cb = np.take_along_axis(cb, keep[:, None, :], axis=2)
        minimum = np.full(len(indices), np.inf, dtype=np.longdouble)
        for tri in (ca, cb):
            for i, j in ((0, 1), (1, 2), (2, 0)):
                edge = tri[:, j]-tri[:, i]
                axes = np.stack((-edge[:, 1], edge[:, 0]), axis=1)
                norm = np.linalg.norm(axes, axis=1)
                zero = norm == 0
                divisor = np.where(zero, 1, norm)[:, None]
                pa = np.einsum('ijk,ik->ij', ca, axes)/divisor
                pb = np.einsum('ijk,ik->ij', cb, axes)/divisor
                depth = np.minimum(pa.max(axis=1), pb.max(axis=1))-np.maximum(pa.min(axis=1), pb.min(axis=1))
                minimum = np.minimum(minimum, depth)
                result[indices[zero]] = 2
        result[indices[minimum > tolerance]] = 1
        uncertain = (minimum > 0) & (minimum <= tolerance) & (shared[indices] == 0)
        result[indices[uncertain]] = 2
        far = np.maximum(np.max(np.abs(da[indices]), axis=1), np.max(np.abs(db[indices]), axis=1)) > tolerance
        result[indices[far]] = 2
    indices = np.flatnonzero(active & ~coplanar & (shared < 2))
    if len(indices):
        d = direction[indices]/length[indices, None]
        intervals = []
        for tri, distances in ((a[indices], da[indices]), (b[indices], db[indices])):
            projections = np.einsum('ijk,ik->ij', tri, d)
            low = np.min(np.where(distances == 0, projections, np.inf), axis=1)
            high = np.max(np.where(distances == 0, projections, -np.inf), axis=1)
            for i, j in ((0, 1), (1, 2), (2, 0)):
                cross = distances[:, i]*distances[:, j] < 0
                denominator = distances[:, i]-distances[:, j]
                fraction = distances[:, i]/np.where(denominator == 0, 1, denominator)
                value = projections[:, i]+fraction*(projections[:, j]-projections[:, i])
                low = np.minimum(low, np.where(cross, value, np.inf))
                high = np.maximum(high, np.where(cross, value, -np.inf))
            intervals.append((low, high))
        overlap = np.minimum(intervals[0][1], intervals[1][1])-np.maximum(intervals[0][0], intervals[1][0])
        contact = (overlap == 0) & (shared[indices] == 0)
        result[indices[(overlap > tolerance) | contact]] = 1
        uncertain = (overlap > 0) & (overlap <= tolerance) & (shared[indices] == 0)
        result[indices[uncertain]] = 2
    return result


def intersection_issues(triangles, connectivity, element_ids):
    """Return bounded diagnostics per failure kind, retaining element IDs.

    BVH leaf pairs are accumulated in bounded batches for vectorized predicates.
    No dense triangle-pair matrix or global intersection-point array is built.
    """
    found = {}
    left_parts, right_parts, count = [], [], 0

    def examine(left, right):
        shared = np.count_nonzero(np.any(connectivity[left, :, None] == connectivity[right, None, :], axis=2), axis=1)
        verdicts = _batch(triangles[left], triangles[right], shared)
        for verdict, code in ((1, 'triangle_intersection'), (2, 'uncertain_triangle_intersection')):
            matches = np.flatnonzero(verdicts == verdict)
            if len(matches) and code not in found:
                index = matches[0]
                i, j = left[index], right[index]
                status = 'incomplete' if verdict == 2 else 'blocked'
                message = f'요소 {int(element_ids[i])}, {int(element_ids[j])}의 면 교차/중첩/비공유 접촉' + (
                    ' 판정이 수치적으로 불확실합니다' if status == 'incomplete' else '이 있습니다')
                found[code] = Issue(code, message, status)

    for left, right in _TriangleBoxes(triangles).pairs():
        left_parts.append(left)
        right_parts.append(right)
        count += len(left)
        if count >= 4096:
            examine(np.concatenate(left_parts), np.concatenate(right_parts))
            left_parts, right_parts, count = [], [], 0
            # A confirmed forbidden intersection is sufficient to block.
            # Keep searching after uncertainty alone, so a definite failure
            # can still be reported without enumerating every crossing pair.
            if 'triangle_intersection' in found:
                return tuple(found.values())
    if count:
        examine(np.concatenate(left_parts), np.concatenate(right_parts))
    return tuple(found.values())
