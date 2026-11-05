"""Stream the complete deviation grid without an element-count memory assumption."""
import numpy as np

from .errors import MeshBlocked


# Preserve the original 128-element batches at the default 19-node face grid.
# This is a working-array budget, not a limit on requested verification nodes.
_SAMPLE_POINTS = 128 * 190


def _weights(dimension, n):
    """Yield the original grid in order, including exact endpoint arithmetic."""
    if dimension == 1:
        step = 1. / (n - 1)
        for start in range(0, n, _SAMPLE_POINTS):
            stop = min(start + _SAMPLE_POINTS, n)
            values = np.arange(start, stop, dtype=float) * step
            if stop == n:
                values[-1] = 1.
            yield values
    else:
        rows = []
        for i in range(n):
            for j in range(n - i):
                rows.append((1-i/(n-1)-j/(n-1), i/(n-1), j/(n-1)))
                if len(rows) == _SAMPLE_POINTS:
                    yield np.array(rows)
                    rows = []
        if rows:
            yield np.array(rows)


def deviation_batches(dimension, tag, xyz, n, projector, *, seeds=False, audit_factory=None):
    """Yield element maxima and first maximizing projected points, never a verdict.

    Large grids also split within one element. Strict '>' retains the first
    maximum across tiles, matching argmax on the original complete sample row.
    Exact-duplicate projection reuse is confined to each bounded CAD batch.
    """
    count = n if dimension == 1 else n * (n + 1) // 2
    batch_size = min(128, max(1, _SAMPLE_POINTS // count))
    small_weights = next(_weights(dimension, n)) if count <= _SAMPLE_POINTS else None
    for start in range(0, len(xyz), 128):
        group = xyz[start:start+128]
        maxima = np.full(len(group), -np.inf)
        locations = np.empty((len(group), 3)) if seeds else None
        audit = (audit_factory() if dimension == 2 and audit_factory is not None
                 and count*len(group) > _SAMPLE_POINTS else None)
        for offset in range(0, len(group), batch_size):
            batch = group[offset:offset+batch_size]
            current_maxima = maxima[offset:offset+len(batch)]
            tiles = (small_weights,) if small_weights is not None else _weights(dimension, n)
            for weights in tiles:
                samples = (np.einsum('ij,ejk->eik', weights, batch) if dimension == 2 else
                           batch[:, :1]+weights[None, :, None]*(batch[:, 1:]-batch[:, :1]))
                unique, inverse = np.unique(samples.reshape(-1, 3), axis=0, return_inverse=True)
                projected, _ = (projector(dimension, tag, unique) if audit is None else
                                projector(dimension, tag, unique, audit=audit))
                distances = np.linalg.norm(projected-unique, axis=1)[inverse].reshape(samples.shape[:2])
                current = distances.max(axis=1)
                if not np.isfinite(current).all():
                    raise MeshBlocked('deviation_incomplete: 표본 편차가 유한하지 않습니다')
                changed = current > current_maxima
                if seeds:
                    argmax = distances.argmax(axis=1)
                    points = projected[inverse.reshape(samples.shape[:2])[np.arange(len(batch)), argmax]]
                    locations[offset:offset+len(batch)][changed] = points[changed]
                current_maxima[changed] = current[changed]
        if audit is not None:
            # Retain the old logical 128-element scale and never expose results
            # until its initial/trim parameter round trips have been checked.
            audit.require_pass()
        yield start, maxima, locations
