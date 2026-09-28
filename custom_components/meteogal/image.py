"""Radar de MeteoGalicia por ubicación, como entidades `image` (docs/radar.md).

Como ha-radarcat: la tarjeta estándar `picture-entity` muestra y anima el WEBP
sin nada más. El estado de la entidad es la hora de la última pasada.
"""

from __future__ import annotations

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import MeteoGalConfigEntry
from .api import Camera
from .const import ATTRIBUTION, CONF_CAMERA_ID
from .coordinator import CameraCoordinator, RadarCoordinator, RadarImages
from .entity import location_device

# Todo llega de coordinadores: no hay actualizaciones por entidad que limitar.
PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MeteoGalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Por ubicación: el radar (animado y la última pasada) y, si la tiene, la
    cámara."""
    radar = entry.runtime_data.radar
    cameras = entry.runtime_data.cameras
    for subentry_id in entry.runtime_data.locations:
        subentry = entry.subentries[subentry_id]
        entities: list[ImageEntity] = [
            RadarAnimation(radar, subentry),
            RadarLatest(radar, subentry),
        ]
        if cameras and (camera_id := subentry.data.get(CONF_CAMERA_ID)):
            entities.append(CameraImage(cameras, subentry, camera_id))
        async_add_entities(entities, config_subentry_id=subentry_id)


class RadarImage(CoordinatorEntity[RadarCoordinator], ImageEntity):
    """Base: una imagen del radar de una ubicación."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: RadarCoordinator, subentry, key: str) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._subentry_id = subentry.subentry_id
        self._attr_translation_key = key
        self._attr_unique_id = f"{subentry.subentry_id}_{key}"
        self._attr_device_info = location_device(subentry)
        self._update_time()

    @property
    def _images(self) -> RadarImages | None:
        return (self.coordinator.data or {}).get(self._subentry_id)

    @property
    def available(self) -> bool:
        return super().available and self._images is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update_time()
        super()._handle_coordinator_update()

    @callback
    def _update_time(self) -> None:
        # La hora de la pasada: cambia solo cuando hay imagen nueva, y así la
        # tarjeta vuelve a pedirla.
        if images := self._images:
            self._attr_image_last_updated = images.time


class RadarAnimation(RadarImage):
    """Las últimas horas animadas (2 h por defecto)."""

    _attr_content_type = "image/webp"

    def __init__(self, coordinator: RadarCoordinator, subentry) -> None:
        super().__init__(coordinator, subentry, "radar")

    async def async_image(self) -> bytes | None:
        images = self._images
        return images.animation if images else None


class RadarLatest(RadarImage):
    """Solo la última pasada, fija. Desactivada por defecto."""

    _attr_content_type = "image/png"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: RadarCoordinator, subentry) -> None:
        super().__init__(coordinator, subentry, "radar_latest")

    async def async_image(self) -> bytes | None:
        images = self._images
        return images.latest if images else None


class CameraImage(CoordinatorEntity[CameraCoordinator], ImageEntity):
    """Última foto de la cámara de MeteoGalicia elegida para la ubicación.

    HA descarga la foto de su URL cuando cambia la hora de la imagen (~5 min).
    """

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION
    _attr_translation_key = "camera"

    def __init__(
        self, coordinator: CameraCoordinator, subentry, camera_id: str | int
    ) -> None:
        CoordinatorEntity.__init__(self, coordinator)
        ImageEntity.__init__(self, coordinator.hass)
        self._camera_id = camera_id
        self._attr_unique_id = f"{subentry.subentry_id}_camera"
        self._attr_device_info = location_device(subentry)
        self._update()

    @property
    def _camera(self) -> Camera | None:
        return self.coordinator.find(self._camera_id)

    @property
    def available(self) -> bool:
        return super().available and self._camera is not None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        camera = self._camera
        return {"camera_name": camera.name} if camera else {}

    @callback
    def _handle_coordinator_update(self) -> None:
        self._update()
        super()._handle_coordinator_update()

    @callback
    def _update(self) -> None:
        if camera := self._camera:
            if camera.time != self._attr_image_last_updated:
                self._cached_image = None  # foto nueva: HA la vuelve a descargar
            self._attr_image_url = camera.image_url
            self._attr_image_last_updated = camera.time
