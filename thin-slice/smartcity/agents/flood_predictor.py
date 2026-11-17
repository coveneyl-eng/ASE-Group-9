"""Flood Predicting Agent: scikit-learn forecast of river level from Met Éireann rain + Marine Institute tide."""
import numpy as np
from sklearn.ensemble import RandomForestRegressor

from smartcity.agents.base import Agent
from smartcity.models import FloodForecast, SensorReading

agent = Agent("flood-predictor")
state = {"tide_m": 3.0, "water_level_m": 1.0}


def train() -> RandomForestRegressor:
    """Placeholder model on synthetic history. Iteration 4 swaps in replays of archived OPW/Marine storms."""
    rng = np.random.default_rng(42)
    rain, tide, level = rng.uniform(0, 60, 2000), rng.uniform(0.5, 4.8, 2000), rng.uniform(0.3, 2.0, 2000)
    future = level + 0.035 * rain + 0.25 * np.maximum(tide - 3.5, 0) + rng.normal(0, 0.05, 2000)
    return RandomForestRegressor(n_estimators=50, random_state=0).fit(np.column_stack([rain, tide, level]), future)


model = train()


def grade(level: float) -> str:
    return "major" if level >= 2.5 else "minor" if level >= 1.8 else "none"


def handle(topic: str, r: SensorReading) -> None:
    if r.kind in ("tide_m", "water_level_m"):
        state[r.kind] = r.value
        return
    if r.kind != "rain_forecast_mm":
        return
    predicted = float(model.predict([[r.value, state["tide_m"], state["water_level_m"]]])[0])
    forecast = FloodForecast(trace_id=r.trace_id, horizon_hours=6, predicted_level_m=round(predicted, 2),
                             expected_impact=grade(predicted))
    agent.publisher.publish("flood.forecast", forecast)
    agent.decide(r.trace_id, {"rain_mm": r.value, **state, "predicted_level_m": forecast.predicted_level_m})
    agent.log.info("6h forecast %.2f m (%s)", predicted, forecast.expected_impact)


if __name__ == "__main__":
    agent.run(["flood.readings"], handle)
