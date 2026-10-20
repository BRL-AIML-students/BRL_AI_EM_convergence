"""Developer-only FLTK render check in an owned process; outputs stay in .cache."""
from pathlib import Path
import json

import gmsh

from brl_mesh.config import Configuration
from brl_mesh import native_ui as ui


def main():
    output = Path('.cache/reassessment/display').resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = Configuration.from_dict({'schema_version': 1,
        'geometry': {'kind': 'cube', 'side': 2}, 'mesh': {'target_size': .4}})
    gmsh.initialize(readConfigFiles=False)
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        gmsh.option.setNumber('General.SaveOptions', 0)
        controller = ui.Controller(config, Path.cwd())
        gmsh.fltk.initialize()
        for kind, numbers in [('cube', {ui.CUBE_SIDE: 2, ui.TARGET: .4}),
                              ('ogive', {ui.DIAMETER: 50, ui.OGIVE_LENGTH: 100, ui.TARGET: 10}),
                              ('sphere', {ui.SPHERE_RADIUS: 1, ui.TARGET: .2}),
                              ('dihedral', {ui.DIHEDRAL_LENGTH: 10, ui.DIHEDRAL_WIDTH1: 2,
                                            ui.DIHEDRAL_WIDTH2: 2, ui.DIHEDRAL_ANGLE: 179,
                                            ui.TARGET: .4})]:
            gmsh.onelab.setString(ui.KIND, [kind])
            controller.invalidate_if_changed(deep=False)
            # This probe isolates framing from the separate curvature acceptance case.
            gmsh.onelab.setNumber(ui.CURVATURE_ENABLED, [0])
            for control, value in numbers.items():
                gmsh.onelab.setNumber(control, [value])
            for axis in 'XYZ':
                gmsh.option.setNumber('General.Scale'+axis, 100)
                gmsh.option.setNumber('General.Translation'+axis, 100)
            controller.perform(2)
            assert controller.last_mesh is not None
            gmsh.fltk.update()
            gmsh.graphics.draw()
            gmsh.fltk.wait(.1)
            path = output/(kind+'.png')
            gmsh.write(str(path))
            assert path.stat().st_size > 1000
            print(json.dumps({'geometry': kind, 'image': str(path),
                              'bbox': gmsh.model.getBoundingBox(-1, -1)}), flush=True)
    finally:
        gmsh.finalize()


if __name__ == '__main__':
    main()
