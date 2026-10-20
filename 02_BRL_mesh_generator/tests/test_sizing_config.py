import copy
import json
import pytest

from brl_mesh.config import Configuration
from brl_mesh.errors import ConfigurationError

BASE={'schema_version':1,'geometry':{'kind':'plate','length':1,'width':1},'mesh':{}}


@pytest.mark.parametrize('mesh',[
    [],{'target_size':None},{'target_size':0},{'minimum_size':-1},
    {'fallback_fraction':0},{'fallback_fraction':1.1},{'minimum_size':True},
    {'wave':[]},{'wave':{}},{'wave':{'frequency_hz':True}},{'wave':{'frequency_hz':0}},
    {'wave':{'frequency_hz':1e9,'relative_permittivity':-1}},
    {'wave':{'frequency_hz':1e9,'relative_permeability':float('inf')}},
    {'wave':{'frequency_hz':1e9,'elements_per_wavelength':0}},
    {'wave':{'frequency_hz':1e9,'loss_tangent':.1}},
    {'local':[]},{'local':{'widths':None}},{'local':{'widths':{'enabled':1}}},
    {'local':{'widths':{'divisions':.5}}},{'local':{'short_edges':{'divisions':True}}},
    {'local':{'widths':{'entities':[1,1]}}},{'local':{'widths':{'entities':[True]}}},
    {'local':{'gaps':{'pairs':[[1,1]]}}},{'local':{'gaps':{'pairs':[[1,2],[2,1]]}}},
    {'local':{'gaps':{'pairs':[[1]]}}},{'local':{'gaps':{'pairs':[[1,False]]}}},
    {'local':{'curves':{}}},{'local':{'curves':[{'entity':0,'size':.1}]}},
    {'local':{'curves':[{'entity':1,'size':.1},{'entity':1,'size':.2}]}},
    {'local':{'curves':[{'entity':1.0,'size':.1}]}},
    {'local':{'boxes':[{'bounds':[0,0,1,1,1,0],'size':.1}]}},
    {'local':{'boxes':[{'bounds':[0,0,0,1,1],'size':.1}]}},
    {'local':{'boxes':[{'bounds':[0,0,0,1,1,1],'size':float('nan')}]}},
    {'local':{'hold_distance':-1}},{'local':{'transition_distance':0}},
    {'local':{'growth_rate':0}},{'local':{'sampling_fraction':.6}},
    {'local':{'max_sampling':7}},{'local':{'max_sampling':True}},
    {'local':{'max_pair_tests':0}},{'local':{'max_features':1.5}},
    {'local':{'curvature':True}}, {'compare':True}
])
def test_invalid_sizing_schema_is_rejected_without_worker_execution(mesh):
    with pytest.raises(ConfigurationError):Configuration.from_dict(BASE|{'mesh':mesh})


def test_advanced_sizing_round_trip_preserves_entity_selection():
    mesh={'wave':{'frequency_hz':1e9,'relative_permittivity':2},'minimum_size':.01,
        'fallback_fraction':.2,'local':{'short_edges':{'enabled':True,'entities':[2],'divisions':4},
        'widths':{'enabled':True,'entities':[1],'divisions':6},'gaps':{'enabled':True,'pairs':[[1,2]],'divisions':4},
        'curves':[{'entity':3,'size':.2}],'boxes':[{'bounds':[0,0,0,1,1,1],'size':.3}],
        'hold_distance':0,'transition_distance':2,'sampling_fraction':.125}}
    config=Configuration.from_dict(BASE|{'mesh':mesh})
    assert Configuration.from_dict(json.loads(json.dumps(config.to_dict())))==config
    assert 'target_size' not in config.to_dict()['mesh']


def test_nested_duplicate_keys_are_never_silently_merged(tmp_path):
    source=tmp_path/'bad.json'
    source.write_text('{"schema_version":1,"geometry":{"kind":"plate","length":1,"width":1},'
                      '"mesh":{"local":{"widths":{"enabled":true,"enabled":false}}}}',encoding='utf-8')
    with pytest.raises(ConfigurationError,match='중복'):Configuration.load(source)
