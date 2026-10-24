"""In-memory champion service with atomic reload and previous-model preservation."""

import asyncio
import logging
from contextlib import suppress
from typing import Any

import pandas as pd

from house_price.domain import FEATURE_NAMES
from house_price.registry.loader import ChampionLoader, LoadedChampion

LOGGER = logging.getLogger(__name__)


class ModelNotReadyError(RuntimeError):
    pass


class ModelService:
    def __init__(self, loader: ChampionLoader, *, poll_seconds: float = 2.0) -> None:
        self.loader = loader
        self.poll_seconds = poll_seconds
        self._watcher: asyncio.Task[None] | None = None

    @property
    def champion(self) -> LoadedChampion | None:
        return self.loader.current

    def load_initial(self) -> None:
        try:
            self.loader.load()
        except FileNotFoundError:
            LOGGER.info("champion_not_available", extra={"stage": "startup"})

    async def start(self) -> None:
        self.load_initial()
        self._watcher = asyncio.create_task(self._watch(), name="champion-watcher")

    async def stop(self) -> None:
        if self._watcher:
            self._watcher.cancel()
            with suppress(asyncio.CancelledError):
                await self._watcher

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(self.poll_seconds)
            try:
                if self.loader.reload_if_changed():
                    champion = self.loader.current
                    LOGGER.info(
                        "champion_reloaded",
                        extra={
                            "model_version": champion.manifest.model_version if champion else None,
                            "training_run_id": str(champion.manifest.training_run_id)
                            if champion
                            else None,
                        },
                    )
            except Exception:
                LOGGER.exception("champion_reload_failed", extra={"stage": "reload"})

    def predict(self, instances: list[dict[str, Any]]) -> list[float]:
        champion = self.champion
        if champion is None:
            raise ModelNotReadyError("no valid champion is loaded")
        frame = pd.DataFrame(instances, columns=FEATURE_NAMES)
        return [float(value) for value in champion.predictor.predict(frame)]

