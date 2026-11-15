import unittest
from unittest.mock import patch
from api import catalog
class TestCatalog(unittest.TestCase):
    @patch.object(catalog,"_request",return_value={"events":[{"id":"e1"}]})
    def test_source(self,req):
        data=catalog.collect("landslides",status="all",days=90)
        self.assertEqual(len(data["events"]),1)
        self.assertIn("days=90",req.call_args.args[0])
    def test_invalid(self):
        for name in ("../etc/passwd","http://test",""):
            with self.assertRaises(ValueError):catalog.collect(name)
        with self.assertRaises(ValueError):catalog.collect("floods",days=800)
        with self.assertRaises(ValueError):catalog.collect("floods",start="1990-01-01",end="2020-01-01")
    @patch.object(catalog,"_request",return_value={"error":"upstream"})
    def test_invalid_schema(self,req):
        with self.assertRaises(RuntimeError):catalog.collect("floods")
