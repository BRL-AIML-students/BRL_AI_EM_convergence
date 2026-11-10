"""Measurements on a prepared Gmsh mesh for development comparisons."""
from __future__ import annotations

import gmsh
import numpy as np

from .curvature import project
from .errors import MeshBlocked
from .model import SurfaceMesh, surface_groups
from .quality import read_radius_ratio


def _distribution(values, percentiles):
    if not len(values):
        return {'count': 0}
    return {'count': len(values),
            **{f'p{p:02d}': float(v) for p, v in zip(percentiles, np.percentile(values, percentiles))},
            'min': float(values.min()), 'max': float(values.max())}


def _size_compliance(lengths):
    result = _distribution(lengths, (5, 50, 95, 99))
    if len(lengths):
        # Frey–George §19.1.2 / Mmg3d §7.2, symmetric under reciprocal lengths.
        efficiency = float(np.exp(np.mean(np.minimum(lengths, 1 / lengths) - 1)))
        result.update(efficiency_index=efficiency, below_reference_0_91=efficiency < .91,
                      below_band=float(np.mean(lengths < 1 / np.sqrt(2))),
                      above_band=float(np.mean(lengths > np.sqrt(2))))
    return result


def _transition(values):
    result = _distribution(values, (50, 95, 99))
    if len(values):
        result['above_1_5'] = float(np.mean(values > 1.5))
    return result


def _edge_metrics(mesh, scene, area):
    faces = mesh.surface_tags
    oriented = np.stack((mesh.connectivity, np.roll(mesh.connectivity, -1, axis=1)), axis=2)
    edges, inverse, counts = np.unique(np.sort(oriented.reshape(-1, 2), axis=1), axis=0,
                                       return_inverse=True, return_counts=True)
    if np.any(counts > 2):
        raise MeshBlocked('development metrics require manifold mesh edges')
    offsets = np.cumsum(counts) - counts
    owners = np.argsort(inverse, kind='stable') // 3
    pairs = np.flatnonzero(counts == 2)
    left, right = owners[offsets[pairs]], owners[offsets[pairs] + 1]
    pair_size = np.sqrt(np.maximum(area[left], area[right]) / np.minimum(area[left], area[right]))
    across = faces[left] != faces[right]

    endpoints = mesh.coordinates[np.searchsorted(mesh.node_ids, edges)]
    lengths = np.linalg.norm(endpoints[:, 1] - endpoints[:, 0], axis=1)
    # CAD seams can have two owners on the same face. Exclude all classified
    # curve edges from the nominal face-field comparison.
    curve_edges = set()
    for _, tag in gmsh.model.getEntities(1):
        types, _, connectivity = gmsh.model.mesh.getElements(1, tag)
        for kind, nodes in zip(types, connectivity):
            if kind != 1 and len(nodes):
                raise MeshBlocked('development metrics require first-order CAD curve elements')
            curve_edges.update(tuple(sorted(edge)) for edge in np.asarray(nodes).reshape(-1, 2))
    on_curve = np.fromiter((tuple(edge) in curve_edges for edge in edges), bool, count=len(edges))
    eligible = pairs[~across & ~on_curve[pairs]]
    nominal = np.full(len(edges), np.nan)
    region = np.full(len(edges), 'unmeasured', dtype='<U10')
    edge_faces = faces[owners[offsets[eligible]]]
    for face, rows in surface_groups(edge_faces).items():
        for offset in range(0, len(rows), 1024):
            selected = eligible[rows[offset:offset + 1024]]
            start, end = endpoints[selected, 0], endpoints[selected, 1]
            points = np.stack((start, start + .5 * (end - start), end), axis=1)
            flat = points.reshape(-1, 3)
            sizes, regions = scene.sizing.nominal_sizes(flat, np.full(len(flat), face), with_regions=True)
            if scene.curvature is not None:
                curve_sizes = np.array([scene.curvature.size(2, face, point, record=False) for point in flat])
                regions[curve_sizes < sizes] = 'curvature'
                sizes = np.minimum(sizes, curve_sizes)
            # Simpson approximation to the isotropic metric length along the chord.
            nominal[selected] = lengths[selected] * ((1 / sizes).reshape(-1, 3) @ np.array([1, 4, 1])) / 6
            region[selected] = regions.reshape(-1, 3)[:, 1]

    by_region = {}
    for name in ('global', 'core', 'transition', 'curvature'):
        mask = region == name
        if np.any(mask):
            by_region[name] = {'length': _distribution(lengths[mask], (5, 50, 95, 99)),
                               'normalized': _size_compliance(nominal[mask]),
                               'transition': _transition(pair_size[mask[pairs]])}

    order = np.argsort(-pair_size, kind='stable')[:5]
    return {
        'length': _distribution(lengths, (5, 50, 95, 99)),
        'length_over_global_request': _distribution(lengths / scene.sizing.global_size, (5, 50, 95, 99)),
        'normalized_interior': _size_compliance(nominal[eligible]),
        'normalized_coverage': len(eligible) / len(edges),
        'by_midpoint_region': by_region,
        'transition': {'all': _transition(pair_size), 'within_face': _transition(pair_size[~across & ~on_curve[pairs]]),
                       'cad_boundary_or_seam': _transition(pair_size[across | on_curve[pairs]])},
        'largest_transitions': [
            {'node_ids': edges[pairs[i]].tolist(), 'element_ids': mesh.element_ids[[left[i], right[i]]].tolist(),
             'faces': faces[[left[i], right[i]]].tolist(), 'ratio': float(pair_size[i])} for i in order],
    }


def _facet_metrics(mesh, xyz, cross, grid_divisions):
    # Include the centroid and edge midpoints. Omit exact vertices, where a CAD
    # face can have a singular parametrization (e.g. a cone tip or sphere pole).
    weights = np.array([(i, j, grid_divisions-i-j) for i in range(grid_divisions+1)
                        for j in range(grid_divisions-i+1)
                        if max(i, j, grid_divisions-i-j) < grid_divisions]) / grid_divisions
    weights = np.vstack((np.full((1, 3), 1/3), weights))
    per_face = {}
    for face, indices in surface_groups(mesh.surface_tags).items():
        angles = np.full(len(indices), np.nan)
        distances = np.empty(len(indices))
        angle_locations = np.empty((len(indices), 3))
        distance_locations = np.empty((len(indices), 3))
        unavailable = 0
        facet = cross[indices] / np.linalg.norm(cross[indices], axis=1)[:, None]
        for offset in range(0, len(indices), 128):
            batch = slice(offset, offset+128)
            points = np.einsum('ij,ejk->eik', weights, xyz[indices[batch]])
            unique, inverse = np.unique(points.reshape(-1, 3), axis=0, return_inverse=True)
            projected, uv = project(2, face, unique)
            cad = np.asarray(gmsh.model.getNormal(face, uv.ravel())).reshape(len(unique), 3)
            norm = np.linalg.norm(cad, axis=1)
            good = np.isfinite(norm) & (norm > 0)
            unit = np.full_like(cad, np.nan)
            unit[good] = cad[good] / norm[good, None]
            refs = unit[inverse].reshape(points.shape)
            # Angular difference between tangent planes. The separate generator
            # orientation check enforces the actual outward/sheet sign.
            direction = np.abs(np.einsum('eij,ej->ei', refs, facet[batch]))
            sine = np.linalg.norm(np.cross(refs, facet[batch, None, :]), axis=2)
            theta = np.degrees(np.arctan2(sine, direction))
            unavailable += int(np.count_nonzero(~np.isfinite(theta)))
            error = np.linalg.norm(unique - projected, axis=1)[inverse].reshape(points.shape[:2])
            for sample_values, maxima, locations in ((theta, angles, angle_locations),
                                                       (error, distances, distance_locations)):
                finite_values = np.where(np.isfinite(sample_values), sample_values, -np.inf)
                worst = np.argmax(finite_values, axis=1)
                row = np.arange(len(worst))
                maxima[batch] = sample_values[row, worst]
                locations[batch] = points[row, worst]

        result = {'sample_count': len(indices) * len(weights), 'unavailable_normal_samples': unavailable}
        for key, values, locations in (('distance', distances, distance_locations),
                                        ('normal_degrees', angles, angle_locations)):
            valid = np.isfinite(values)
            result[key] = _distribution(values[valid], (95,))
            if np.any(valid):
                worst = np.argmax(np.where(valid, values, -np.inf))
                result[key].update(element_id=int(mesh.element_ids[indices[worst]]),
                                   sample_point=locations[worst].tolist())
                if key == 'normal_degrees':
                    result[key]['fraction_above_degrees'] = {
                        cutoff: float(np.mean(values[valid] > cutoff)) for cutoff in (5, 10, 15)
                    }
        per_face[face] = result
    return per_face


def measure_development_metrics(mesh: SurfaceMesh, scene, *, normal_grid=4):
    """Use on the accepted mesh; diagnostics do not participate in acceptance."""
    if not isinstance(normal_grid, int) or not 2 <= normal_grid <= 16 or normal_grid % 2:
        raise ValueError('normal_grid must be an even integer from 2 to 16')
    mesh.validate()
    radius = read_radius_ratio(mesh)
    scene.sizing.require_current()
    xyz = mesh.triangles()
    cross = np.cross(xyz[:, 1] - xyz[:, 0], xyz[:, 2] - xyz[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    return {'edges': _edge_metrics(mesh, scene, area),
            'radius_ratio': {**_distribution(radius, (5,)), 'below_0_50': int(np.count_nonzero(radius < .5)),
                             'minimum_element_id': int(mesh.element_ids[radius.argmin()])},
            'normal_grid_divisions': normal_grid,
            'facets_by_face': _facet_metrics(mesh, xyz, cross, normal_grid)}
