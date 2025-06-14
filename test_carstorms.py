#!/usr/bin/env python3
import unittest
from unittest.mock import patch, mock_open
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from carstorms import (
    load_config,
    knots_to_kmh,
    classify_storm,
    analyze_proximity,
    main
)

class TestCarStorms(unittest.TestCase):
    def setUp(self):
        # Use the real config for all tests
        alert_radius, wind_threshold, locations, webhook_url = load_config()
        self.test_config = {
            "alert_radius_km": alert_radius,
            "wind_threshold_kt": wind_threshold,
            "locations": {k: list(v) for k, v in locations.items()},
            "webhook_url": webhook_url
        }
        # Sample test coordinates and times
        self.test_coords = [
            (-64.73, 18.33),  # Close to test location
            (-65.73, 19.33),  # Further away
        ]
        self.test_times = [
            datetime.now(timezone.utc),
            datetime.now(timezone.utc)
        ]

    def test_load_config(self):
        alert_radius, wind_threshold, locations, webhook_url = load_config()
        self.assertEqual(alert_radius, 150)
        self.assertEqual(wind_threshold, 60)
        self.assertIn("St. John (USVI)", locations)
        self.assertIn("St. Barths", locations)
        self.assertTrue(webhook_url.startswith("http"))

    def test_knots_to_kmh(self):
        self.assertEqual(knots_to_kmh(100), 185)
        self.assertEqual(knots_to_kmh(0), 0)

    def test_classify_storm(self):
        # Test Category 5
        self.assertIn("Category 5", classify_storm(252))
        # Test Category 1
        self.assertIn("Category 1", classify_storm(120))
        # Test Tropical Storm
        self.assertIn("Tropical Storm", classify_storm(70))
        # Test below threshold
        self.assertIn("not considered dangerous", classify_storm(50))

    def test_analyze_proximity(self):
        # Use the refactored function signature
        results = analyze_proximity(
            self.test_coords,
            self.test_times,
            {"Test Location": (18.33, -64.73)},
            150
        )
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0]["location"], "Test Location")

    def test_main_with_mock_data(self):
        # Simulate a real storm scenario in the KML with <TimeSpan> and <when> tags as expected
        mock_kml = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
        <kml xmlns=\"http://www.opengis.net/kml/2.2\">
            <Document>
                <Placemark>
                    <name>Hurricane Test</name>
                    <description><![CDATA[Maximum sustained winds: 130 knots]]></description>
                    <LineString>
                        <coordinates>-64.73,18.33,0 -65.00,18.50,0</coordinates>
                    </LineString>
                    <when>2024-08-01T12:00:00Z</when>
                    <when>2024-08-01T18:00:00Z</when>
                </Placemark>
            </Document>
        </kml>
        """
        from unittest.mock import patch
        with patch('carstorms.requests.get') as mock_get:
            mock_get.return_value.content = b'dummy'
            # Mock ZipFile to return our KML data
            with patch('carstorms.ZipFile') as mock_zip:
                mock_zip_instance = mock_zip.return_value
                mock_zip_instance.namelist.return_value = ['nhc.kml']
                mock_zip_instance.read.return_value = mock_kml.encode('utf-8')
                # Mock file operations and capture logs
                with patch('builtins.open', mock_open()):
                    with patch('json.dump') as mock_json_dump:
                        from carstorms import main  # re-import to get the refactored version
                        # Patch analyze_proximity to print its input
                        import carstorms as cs
                        orig_analyze_proximity = cs.analyze_proximity
                        def debug_analyze_proximity(coords, times, locations, alert_radius_km):
                            print(f"\n[DEBUG] coords: {coords}")
                            print(f"[DEBUG] times: {times}")
                            print(f"[DEBUG] locations: {locations}")
                            return orig_analyze_proximity(coords, times, locations, alert_radius_km)
                        cs.analyze_proximity = debug_analyze_proximity
                        main(config=self.test_config)
                        cs.analyze_proximity = orig_analyze_proximity
                        # Print all debug logs
                        print("\nDebug logs:")
                        # Check that the output contains the simulated storm and affected location
                        args, kwargs = mock_json_dump.call_args
                        output_json = args[0]
                        print("\nOutput JSON:", json.dumps(output_json, indent=2))
                        self.assertEqual(output_json["storms"][0]["name"], "Hurricane Test")
                        self.assertIn(output_json["storms"][0]["locations"][0]["location"], ["St. John (USVI)", "St. Barths"])
                        self.assertGreaterEqual(output_json["storms"][0]["wind_kt"], 119)
                        self.assertIn("Category", output_json["storms"][0]["category_description"])

if __name__ == '__main__':
    unittest.main() 