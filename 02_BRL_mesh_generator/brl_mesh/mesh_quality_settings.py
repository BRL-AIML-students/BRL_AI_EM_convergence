"""Independent, user-controlled mesh quality gates; never EM accuracy claims."""
from dataclasses import asdict, dataclass

from .mesh_generator_errors import ConfigurationError
from .configuration_value_validation import object_value, number, boolean


@dataclass(frozen=True)
class QualitySettings:
    icn_enabled: bool = True
    icn_minimum: float = 0.0
    aspect_ratio_enabled: bool = True
    aspect_ratio_maximum: float = 3.0
    minimum_angle_enabled: bool = True
    minimum_angle_degrees: float = 20.0
    radius_ratio_enabled: bool = False
    radius_ratio_minimum: float = 0.5

    def __post_init__(self):
        for key in ('icn_enabled', 'aspect_ratio_enabled', 'minimum_angle_enabled', 'radius_ratio_enabled'):
            boolean(getattr(self, key), 'quality.' + key)
        for key in ('icn_minimum', 'radius_ratio_minimum'):
            value = number(getattr(self, key), 'quality.' + key)
            if not 0 <= value <= 1:
                raise ConfigurationError(f'quality.{key}: 0 이상 1 이하여야 합니다')
        if number(self.aspect_ratio_maximum, 'quality.aspect_ratio_maximum') < 1:
            raise ConfigurationError('quality.aspect_ratio_maximum: 1 이상이어야 합니다')
        if not 0 <= number(self.minimum_angle_degrees, 'quality.minimum_angle_degrees') <= 60:
            raise ConfigurationError('quality.minimum_angle_degrees: 0 이상 60 이하여야 합니다')

    def to_dict(self):
        return asdict(self)


def parse_quality_settings(value):
    return QualitySettings(**object_value(value, set(QualitySettings.__dataclass_fields__), set(), 'quality'))
