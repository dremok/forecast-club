from collections import defaultdict

from app.models import Forecast, PredictionStatus
from app.schemas import CalibrationBucket


def calculate_brier_score(probability: float, outcome: PredictionStatus) -> float | None:
    """
    Calculate Brier score for a single forecast.
    Brier score = (probability - actual)²

    - 0 = perfect prediction
    - 0.25 = no information (always predicting 50%)
    - 1 = maximally wrong

    Returns None for ambiguous outcomes.
    """
    if outcome == PredictionStatus.ambiguous:
        return None

    actual = 1.0 if outcome == PredictionStatus.resolved_yes else 0.0
    return (probability - actual) ** 2


def calculate_average_brier_score(forecasts: list[tuple[float, PredictionStatus]]) -> float | None:
    """
    Calculate average Brier score across multiple forecasts.
    Excludes ambiguous outcomes.
    """
    scores = []
    for probability, outcome in forecasts:
        score = calculate_brier_score(probability, outcome)
        if score is not None:
            scores.append(score)

    if not scores:
        return None

    return sum(scores) / len(scores)


def calculate_calibration_buckets(
    forecasts: list[tuple[float, PredictionStatus]],
    num_buckets: int = 10
) -> list[CalibrationBucket]:
    """
    Calculate calibration data by grouping forecasts into probability buckets.

    For each bucket, compares the average predicted probability to the actual
    frequency of positive outcomes.

    A perfectly calibrated forecaster would have predicted probability ≈ actual frequency
    in each bucket.
    """
    bucket_size = 1.0 / num_buckets
    buckets: dict[int, list[tuple[float, float]]] = defaultdict(list)

    for probability, outcome in forecasts:
        if outcome == PredictionStatus.ambiguous:
            continue

        actual = 1.0 if outcome == PredictionStatus.resolved_yes else 0.0
        bucket_idx = min(int(probability / bucket_size), num_buckets - 1)
        buckets[bucket_idx].append((probability, actual))

    result = []
    for i in range(num_buckets):
        bucket_start = i * bucket_size
        bucket_end = (i + 1) * bucket_size

        items = buckets.get(i, [])
        if not items:
            continue

        predicted_avg = sum(p for p, _ in items) / len(items)
        actual_freq = sum(a for _, a in items) / len(items)

        result.append(CalibrationBucket(
            bucket_start=bucket_start,
            bucket_end=bucket_end,
            predicted_probability=predicted_avg,
            actual_frequency=actual_freq,
            count=len(items)
        ))

    return result


def get_forecast_with_score(forecast: Forecast) -> tuple[Forecast, float | None]:
    """
    Return a forecast with its Brier score calculated.
    """
    prediction = forecast.prediction
    if prediction.status == PredictionStatus.open:
        return forecast, None

    score = calculate_brier_score(forecast.probability, prediction.status)
    return forecast, score
