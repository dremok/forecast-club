import pytest

from app.models import PredictionStatus
from app.scoring import (
    calculate_average_brier_score,
    calculate_brier_score,
    calculate_calibration_buckets,
)


class TestBrierScore:
    def test_perfect_prediction_yes(self):
        # Predicted 100%, outcome was yes
        score = calculate_brier_score(1.0, PredictionStatus.resolved_yes)
        assert score == 0.0

    def test_perfect_prediction_no(self):
        # Predicted 0%, outcome was no
        score = calculate_brier_score(0.0, PredictionStatus.resolved_no)
        assert score == 0.0

    def test_worst_prediction_yes(self):
        # Predicted 0%, outcome was yes
        score = calculate_brier_score(0.0, PredictionStatus.resolved_yes)
        assert score == 1.0

    def test_worst_prediction_no(self):
        # Predicted 100%, outcome was no
        score = calculate_brier_score(1.0, PredictionStatus.resolved_no)
        assert score == 1.0

    def test_no_information_prediction_yes(self):
        # Predicted 50%, outcome was yes
        score = calculate_brier_score(0.5, PredictionStatus.resolved_yes)
        assert score == 0.25

    def test_no_information_prediction_no(self):
        # Predicted 50%, outcome was no
        score = calculate_brier_score(0.5, PredictionStatus.resolved_no)
        assert score == 0.25

    def test_typical_prediction(self):
        # Predicted 70%, outcome was yes
        score = calculate_brier_score(0.7, PredictionStatus.resolved_yes)
        assert abs(score - 0.09) < 0.001

    def test_ambiguous_returns_none(self):
        score = calculate_brier_score(0.5, PredictionStatus.ambiguous)
        assert score is None


class TestAverageBrierScore:
    def test_single_forecast(self):
        forecasts = [(0.8, PredictionStatus.resolved_yes)]
        avg = calculate_average_brier_score(forecasts)
        assert abs(avg - 0.04) < 0.001  # (0.8 - 1)^2

    def test_multiple_forecasts(self):
        forecasts = [
            (1.0, PredictionStatus.resolved_yes),  # 0.0
            (0.0, PredictionStatus.resolved_no),   # 0.0
        ]
        avg = calculate_average_brier_score(forecasts)
        assert avg == 0.0

    def test_mixed_forecasts(self):
        forecasts = [
            (0.9, PredictionStatus.resolved_yes),  # 0.01
            (0.1, PredictionStatus.resolved_no),   # 0.01
        ]
        avg = calculate_average_brier_score(forecasts)
        assert abs(avg - 0.01) < 0.001

    def test_excludes_ambiguous(self):
        forecasts = [
            (1.0, PredictionStatus.resolved_yes),
            (0.5, PredictionStatus.ambiguous),  # Should be excluded
            (0.0, PredictionStatus.resolved_no),
        ]
        avg = calculate_average_brier_score(forecasts)
        assert avg == 0.0

    def test_all_ambiguous_returns_none(self):
        forecasts = [
            (0.5, PredictionStatus.ambiguous),
            (0.7, PredictionStatus.ambiguous),
        ]
        avg = calculate_average_brier_score(forecasts)
        assert avg is None

    def test_empty_list_returns_none(self):
        avg = calculate_average_brier_score([])
        assert avg is None


class TestCalibrationBuckets:
    def test_perfectly_calibrated(self):
        # For each probability bucket, actual frequency matches
        # Use 0.05 which falls into bucket 0 (0.0-0.1)
        forecasts = [
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_no),
            (0.05, PredictionStatus.resolved_yes),  # 10% actual
        ]
        buckets = calculate_calibration_buckets(forecasts, num_buckets=10)

        # Should have one bucket for 0.0-0.1
        assert len(buckets) == 1
        bucket = buckets[0]
        assert bucket.bucket_start == 0.0
        assert bucket.bucket_end == 0.1
        assert bucket.count == 10
        assert abs(bucket.actual_frequency - 0.1) < 0.001

    def test_excludes_ambiguous(self):
        forecasts = [
            (0.5, PredictionStatus.resolved_yes),
            (0.5, PredictionStatus.ambiguous),  # Should be excluded
        ]
        buckets = calculate_calibration_buckets(forecasts, num_buckets=10)

        total_count = sum(b.count for b in buckets)
        assert total_count == 1

    def test_empty_list(self):
        buckets = calculate_calibration_buckets([])
        assert buckets == []

    def test_multiple_buckets(self):
        forecasts = [
            (0.15, PredictionStatus.resolved_no),
            (0.85, PredictionStatus.resolved_yes),
        ]
        buckets = calculate_calibration_buckets(forecasts, num_buckets=10)

        assert len(buckets) == 2
        bucket_starts = [b.bucket_start for b in buckets]
        assert 0.1 in bucket_starts  # 0.15 falls in 0.1-0.2
        assert 0.8 in bucket_starts  # 0.85 falls in 0.8-0.9
