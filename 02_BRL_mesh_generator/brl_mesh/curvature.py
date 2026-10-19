"""Local CAD curvature requests and bounded sampled-deviation feedback.

The callback is an initial size estimate, never a maximum-error proof. Direct
CAD sampling keeps original element IDs and explicitly checks trimmed domains;
DiscretizationError's list-view output does not expose those contracts.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import math

import gmsh
import numpy as np

from .errors import MeshBlocked
from .model import assert_current
from .resources import checkpoint


def initial_size(curvature, tolerance, dimension, cap):
    """Stable circular chord / surface-centroid initial estimate in CAD units."""
    k = abs(float(curvature))
    if not math.isfinite(k) or not math.isfinite(tolerance) or tolerance <= 0:
        raise MeshBlocked('curvature_incomplete: 유효한 곡률/편차가 필요합니다')
    if k == 0:
        return cap
    # A radius already smaller than delta does not require h -> 0 at a pole.
    # This finite absolute-resolution treatment is checked by actual sampling.
    if tolerance*k >= 1:
        return min(cap, tolerance)
    factor = 8-4*tolerance*k if dimension == 1 else 6
    # Compare before division/sqrt to avoid overflow for almost-flat geometry.
    root = math.sqrt(tolerance)/math.sqrt(k)*math.sqrt(factor)
    return min(cap, root)


def circle_divisions(radius, tolerance):
    if not math.isfinite(radius) or radius <= 0 or not 0 < tolerance < radius:
        raise MeshBlocked('circle_requirement_incomplete: 0 < delta < R이 필요합니다')
    angle = 2*math.asin(math.sqrt(tolerance/radius/2))
    if not angle > 0:
        raise MeshBlocked('circle_requirement_incomplete: 원호 요구를 수치로 표현하지 못했습니다')
    return math.ceil(math.pi/angle)


def _array(value, columns, count, name):
    result = np.asarray(value, dtype=float)
    if result.size != count*columns or not np.isfinite(result).all():
        raise MeshBlocked(f'projection_incomplete: {name} 결과 누락/비유한 값')
    return result.reshape(count, columns)


def project(dimension, tag, points, *, trimmed=True):
    """Return validated projections, including curve trim endpoints."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    projected, parameters = gmsh.model.getClosestPoint(dimension, tag, points.ravel())
    projected = _array(projected, 3, len(points), 'coordinates')
    # Curve closest-point parameters in this DLL can be uninitialized. Recover
    # from its valid coordinates; the surface API is independently validated.
    if dimension == 1:
        parameters = gmsh.model.getParametrization(1, tag, projected.ravel())
        parameters = _array(parameters, 1, len(points), 'curve parameters')
        low, high = gmsh.model.getParametrizationBounds(1, tag)
        parameters = np.clip(parameters, low[0], high[0])
        projected = _array(gmsh.model.getValue(1, tag, parameters.ravel()), 3, len(points), 'curve value')
    else:
        parameters = _array(parameters, 2, len(points), 'surface parameters')
        reconstructed = _array(gmsh.model.getValue(2, tag, parameters.ravel()), 3, len(points), 'surface value')
        scale = max(float(np.max(np.abs(projected))), float(np.max(np.ptp(points, axis=0))), 1e-300)
        if np.max(np.linalg.norm(reconstructed-projected, axis=1)) > max(
                128*np.finfo(float).eps*scale, gmsh.option.getNumber('Geometry.Tolerance')):
            raise MeshBlocked('projection_incomplete: CAD parameter round-trip 불일치')
        if trimmed:
            count = gmsh.model.isInside(2, tag, parameters.ravel(), parametric=True)
            if not 0 <= count <= len(points):
                raise MeshBlocked('projection_trim_incomplete: trim 분류 개수가 유효하지 않습니다')
            if count != len(points):
                mask = []
                for index, point in enumerate(parameters):
                    if index % 256 == 0:
                        checkpoint()
                    inside = gmsh.model.isInside(2, tag, point, parametric=True)
                    if inside not in (0, 1):
                        raise MeshBlocked('projection_trim_incomplete: trim 점 분류 실패')
                    mask.append(bool(inside))
                if sum(mask) != count:
                    raise MeshBlocked('projection_trim_incomplete: trim batch/point 분류 불일치')
                outside = np.flatnonzero(~np.asarray(mask))
                curves = sorted({abs(edge) for dim, edge in gmsh.model.getBoundary(
                    [(2, tag)], combined=False, oriented=False) if dim == 1})
                if not curves:
                    raise MeshBlocked('projection_trim_incomplete: CAD trim 경계가 없습니다')
                best = np.full(len(outside), np.inf)
                replacements = np.full((len(outside), 3), np.nan)
                for edge in curves:
                    if gmsh.model.occ.getMass(1, edge) <= 0:
                        continue
                    checkpoint(samples=len(outside))
                    candidates, _ = project(1, edge, points[outside])
                    distances = np.linalg.norm(candidates-points[outside], axis=1)
                    use = distances < best
                    replacements[use], best[use] = candidates[use], distances[use]
                if not np.isfinite(best).all():
                    raise MeshBlocked('projection_trim_incomplete: 유효한 CAD trim 경계가 없습니다')
                replacement_uv = _array(gmsh.model.getParametrization(2, tag, replacements.ravel()), 2,
                                        len(outside), 'trim parameters')
                reconstructed = _array(gmsh.model.getValue(2, tag, replacement_uv.ravel()), 3,
                                       len(outside), 'trim value')
                if (np.max(np.linalg.norm(reconstructed-replacements, axis=1)) > max(
                        128*np.finfo(float).eps*scale, gmsh.option.getNumber('Geometry.Tolerance'))
                        or gmsh.model.isInside(2, tag, replacement_uv.ravel(), parametric=True) != len(outside)):
                    raise MeshBlocked('projection_trim_incomplete: 유효한 CAD trim 경계 투영을 구하지 못했습니다')
                projected[outside] = replacements
                parameters = _array(gmsh.model.getParametrization(2, tag, projected.ravel()), 2,
                                    len(points), 'trim parameters')
                # A valid boundary point gives a conservative mesh-to-CAD
                # distance. For a planar face it is the trimmed closest point;
                # no global nearest-point guarantee is inferred on curved CAD.
    return projected, parameters


@dataclass(frozen=True)
class Deviation:
    # Explicit original dimension/entity/element ID mapping, independent of order.
    values: tuple[tuple[int, int, int, float], ...]
    entity_ratios: tuple[tuple[tuple[int, int], float], ...]

    @property
    def ratio(self):
        return max((v for _, v in self.entity_ratios), default=0.)


@dataclass(frozen=True)
class CurvatureRequest:
    required: float
    applied: float
    circle_divisions: int


class CurvaturePlan:
    def __init__(self, config, sizing):
        self.settings = config.sizing.curvature
        self.cap = sizing.global_size
        self.floor = sizing.minimum_size
        self.tolerances, self.scales, self.requests = {}, {}, {}
        self.failure = None
        self.calls = 0
        self.iterations = 0
        self.history = []
        self.faces = {tag for _, tag in gmsh.model.getEntities(2)}
        self.curves = {abs(tag) for face in self.faces for dim, tag in
                       gmsh.model.getBoundary([(2, face)], combined=False, oriented=False) if dim == 1}
        self.curve_faces = {curve: tuple(sorted(face for face in self.faces if curve in
                            {abs(t) for d, t in gmsh.model.getBoundary([(2, face)], combined=False, oriented=False) if d == 1}))
                            for curve in self.curves}
        self.point_curves = {tag: tuple(int(c) for c in gmsh.model.getAdjacencies(0, tag)[0] if c in self.curves)
                             for _, tag in gmsh.model.getEntities(0)}
        magnitude = max(abs(v) for face in self.faces for v in gmsh.model.getBoundingBox(2, face))
        precision = 128*np.finfo(float).eps*max(magnitude, self.cap)
        for dim, tags in ((1, self.curves), (2, self.faces)):
            for tag in sorted(tags):
                mass = gmsh.model.occ.getMass(dim, tag)
                if dim == 1 and (mass == 0 or (mass <= precision and
                        gmsh.model.getType(1, tag) == 'Unknown' and
                        not gmsh.model.getBoundary([(1, tag)], oriented=False))):
                    # OCC represents sphere poles as null curves with round-off
                    # nonzero mass. They have no boundary and no line elements.
                    continue
                length = mass if dim == 1 else math.sqrt(mass)
                candidates = [self.settings.absolute_tolerance] if self.settings.absolute_tolerance else []
                if self.settings.relative_tolerance:
                    candidates.append(self.settings.relative_tolerance*length)
                delta = min(candidates)
                if not math.isfinite(delta) or delta <= precision:
                    raise MeshBlocked('curvature_precision_conflict: 허용 편차가 CAD 좌표 정밀도 이하입니다')
                self.tolerances[dim, tag] = delta
                self.scales[dim, tag] = 1.

    def size(self, dim, tag, point):
        if (dim, tag) not in self.tolerances:
            return self.cap
        # Gmsh can evaluate a size outside a face's trim while constructing it.
        # Curvature there is only an initial request; final samples require trim.
        parameters = _array(gmsh.model.getParametrization(dim, tag, point), dim, 1, 'size parameters')
        if dim == 2:
            maximum, minimum, major, minor = gmsh.model.getPrincipalCurvatures(tag, parameters.ravel())
            major, minor = _array(major, 3, 1, 'principal direction'), _array(minor, 3, 1, 'principal direction')
            if min(np.linalg.norm(major), np.linalg.norm(minor)) < .5:
                # Gmsh 4.15.2 ignores OCC curvature failure at poles and exposes
                # uninitialized cmin/cmax with zero directions. Query just inside
                # the parameter domain instead of consuming those numbers.
                low, high = map(np.asarray, gmsh.model.getParametrizationBounds(2, tag))
                inset = (high-low)*1e-5
                inside = np.clip(parameters.ravel(), low+inset, high-inset)
                maximum, minimum, major, minor = gmsh.model.getPrincipalCurvatures(tag, inside)
                if min(np.linalg.norm(_array(major, 3, 1, 'principal direction')),
                       np.linalg.norm(_array(minor, 3, 1, 'principal direction'))) < .5:
                    raise MeshBlocked('curvature_singularity_incomplete: 주곡률 방향을 구하지 못했습니다')
            k = max(abs(_array(maximum, 1, 1, 'principal curvature')[0, 0]),
                    abs(_array(minimum, 1, 1, 'principal curvature')[0, 0]))
        else:
            k = abs(_array(gmsh.model.getCurvature(dim, tag, parameters.ravel()), 1, 1, 'curve curvature')[0, 0])
        k = float(k)
        required = initial_size(k, self.tolerances[dim, tag], dim, self.cap)
        applied = required*self.scales[dim, tag]
        old = self.requests.get((dim, tag), CurvatureRequest(self.cap, self.cap, 0))
        divisions = (circle_divisions(1/k, self.tolerances[dim, tag])
                     if dim == 1 and required < self.cap and k > 1/np.finfo(float).max
                     and self.tolerances[dim, tag]*k < 1 else 0)
        self.requests[dim, tag] = CurvatureRequest(min(old.required, required), min(old.applied, applied),
                                                  max(old.circle_divisions, divisions))
        if applied < self.floor*(1-1e-12) or not math.isfinite(applied) or applied <= 0:
            raise MeshBlocked(f'curvature_minimum_conflict: required={required:g}, applied={applied:g}, '
                              f'minimum_size={self.floor:g}; 요구를 clamp하지 않습니다')
        return applied

    def target(self, dim, tag, point):
        result = self.size(dim, tag, point) if dim in (1, 2) else self.cap
        curves = (tag,) if dim == 1 else self.point_curves.get(tag, ()) if dim == 0 else ()
        for curve in curves:
            if dim == 0:
                result = min(result, self.size(1, curve, point))
            for face in self.curve_faces.get(curve, ()):
                result = min(result, self.size(2, face, point))
        return result

    @contextmanager
    def callback(self):
        self.failure = None
        def evaluate(dim, tag, x, y, z, lc):
            # ctypes callbacks cannot propagate Python exceptions into Gmsh.
            # Record and block immediately after generate; do not return garbage.
            if self.failure is not None:
                return self.cap
            try:
                self.calls += 1
                if self.calls % 128 == 1:
                    checkpoint()
                return min(lc, self.target(dim, tag, (x, y, z)))
            except Exception as exc:
                self.failure = exc
                return self.cap
        gmsh.model.mesh.setSizeCallback(evaluate)
        try:
            yield
        finally:
            gmsh.model.mesh.removeSizeCallback()
        if self.failure is not None:
            raise MeshBlocked(f'curvature_callback_incomplete: {self.failure}') from self.failure

    def measure(self, mesh, sampling=None):
        assert_current(mesh)
        n = sampling or self.settings.verification_nodes
        weights = np.array([(1-i/(n-1)-j/(n-1), i/(n-1), j/(n-1))
                            for i in range(n) for j in range(n-i)])
        line_weights = np.linspace(0, 1, n)
        result, ratios = [], []
        for dim, tag in sorted(self.tolerances):
            if dim == 2:
                indices = np.flatnonzero(mesh.surface_tags == tag)
                ids, xyz = mesh.element_ids[indices], mesh.triangles()[indices]
                if not len(ids):
                    raise MeshBlocked(f'deviation_incomplete: surface {tag} 요소 누락')
            else:
                types, id_blocks, node_blocks = gmsh.model.mesh.getElements(1, tag)
                if any(kind != 1 and len(ids) for kind, ids in zip(types, id_blocks)):
                    raise MeshBlocked('deviation_incomplete: 1차 line만 지원합니다')
                ids = np.concatenate(id_blocks) if len(id_blocks) else np.array([])
                conn = np.concatenate(node_blocks).reshape(-1, 2) if len(ids) else np.empty((0, 2), int)
                # Independent curves are excluded; face-boundary nodes must exist.
                if not len(ids):
                    raise MeshBlocked(f'deviation_incomplete: CAD curve {tag} line 누락')
                if not np.isin(conn, mesh.node_ids).all():
                    raise MeshBlocked('deviation_incomplete: 경계 line node 대응 실패')
                xyz = mesh.coordinates[np.searchsorted(mesh.node_ids, conn)]
            entity_max = 0.
            for start in range(0, len(ids), 128):
                batch = xyz[start:start+128]
                samples = (np.einsum('ij,ejk->eik', weights, batch) if dim == 2 else
                           batch[:, :1]+line_weights[None, :, None]*(batch[:, 1:]-batch[:, :1]))
                checkpoint(samples=samples.shape[0]*samples.shape[1])
                projected, _ = project(dim, tag, samples.reshape(-1, 3))
                distances = np.linalg.norm(projected-samples.reshape(-1, 3), axis=1).reshape(samples.shape[:2])
                maxima = distances.max(axis=1)
                entity_max = max(entity_max, float(maxima.max()))
                result.extend((dim, tag, int(e), float(v)) for e, v in zip(ids[start:start+128], maxima))
            ratios.append(((dim, tag), entity_max/self.tolerances[dim, tag]))
        checkpoint(mesh=True)
        return Deviation(tuple(result), tuple(ratios))

    def refine(self, deviation):
        if self.iterations >= self.settings.max_iterations:
            raise MeshBlocked(f'curvature_iteration_limit: sampled deviation ratio={deviation.ratio:g}, '
                              f'재생성 {self.iterations}/{self.settings.max_iterations}')
        changes = {}
        for key, ratio in deviation.entity_ratios:
            if ratio > 1+1e-10:
                factor = min(.8, .8/math.sqrt(ratio))
                changes[key] = min(changes.get(key, 1), factor)
                if key[0] == 2:
                    for curve, faces in self.curve_faces.items():
                        if key[1] in faces and (1, curve) in self.scales:
                            changes[1, curve] = min(changes.get((1, curve), 1), factor)
        for key, factor in changes.items():
            self.scales[key] *= factor
        self.iterations += 1

    def deviation_ratio(self, mesh):
        return self.measure(mesh).ratio
