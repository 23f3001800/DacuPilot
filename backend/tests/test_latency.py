import time
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from datapilot.latency import latency_middleware_factory, track_latency


class LatencyTrackingTests(unittest.TestCase):
    def test_track_latency_measures_elapsed_milliseconds(self):
        with track_latency("unit_test_operation") as tracker:
            time.sleep(0.02)

        self.assertEqual(tracker["operation"], "unit_test_operation")
        self.assertGreater(tracker["latency_ms"], 15.0)
        self.assertLess(tracker["latency_ms"], 500.0)

    def test_latency_middleware_adds_header_to_response(self):
        app = FastAPI()
        app.add_middleware(latency_middleware_factory())

        @app.get("/ping")
        async def ping():
            return {"status": "ok"}

        client = TestClient(app)
        response = client.get("/ping")

        self.assertEqual(response.status_code, 200)
        self.assertIn("X-Latency-Ms", response.headers)
        val = float(response.headers["X-Latency-Ms"])
        self.assertGreaterEqual(val, 0.0)


if __name__ == "__main__":
    unittest.main()
