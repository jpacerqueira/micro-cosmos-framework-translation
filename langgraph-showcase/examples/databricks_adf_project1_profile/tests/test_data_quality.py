import unittest
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType
from src.data_quality.quality_checker import DataQualityChecker

class TestDataQualityChecker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.spark = SparkSession.builder \
            .appName("TestDataQuality") \
            .master("local[2]") \
            .getOrCreate()

        # Create test schema
        cls.test_schema = StructType([
            StructField("id", IntegerType(), True),
            StructField("name", StringType(), True),
            StructField("age", IntegerType(), True),
            StructField("score", DoubleType(), True)
        ])

        # Create test data
        cls.test_data = [
            (1, "John", 25, 85.5),
            (2, "Alice", 30, 92.0),
            (3, None, 35, 88.5),
            (4, "Bob", None, 90.0),
            (5, "Carol", 28, None)
        ]
        cls.test_df = cls.spark.createDataFrame(cls.test_data, cls.test_schema)

    def setUp(self):
        """Set up test case."""
        self.checker = DataQualityChecker()

    def test_validate_schema(self):
        """Test schema validation."""
        results = self.checker.validate_schema(self.test_df, self.test_schema)
        self.assertTrue(results["schema_match"])
        self.assertEqual(len(results["missing_columns"]), 0)
        self.assertEqual(len(results["extra_columns"]), 0)
        self.assertEqual(len(results["type_mismatches"]), 0)

    def test_check_completeness(self):
        """Test completeness checks."""
        results = self.checker.check_completeness(self.test_df)
        
        # Check name column completeness
        self.assertEqual(results["name"]["total_count"], 5)
        self.assertEqual(results["name"]["null_count"], 1)
        self.assertAlmostEqual(results["name"]["completeness_ratio"], 0.8)

        # Check age column completeness
        self.assertEqual(results["age"]["total_count"], 5)
        self.assertEqual(results["age"]["null_count"], 1)
        self.assertAlmostEqual(results["age"]["completeness_ratio"], 0.8)

    def test_check_data_quality(self):
        """Test custom quality checks."""
        rules = {
            "id_not_null": {"type": "not_null", "column": "id"},
            "score_range": {"type": "value_range", "column": "score", "min": 0, "max": 100}
        }
        
        results = self.checker.check_data_quality(self.test_df, rules)
        
        # Check id not null rule
        self.assertFalse(results["id_not_null"]["has_nulls"])
        
        # Check score range rule
        self.assertTrue(results["score_range"]["is_in_range"])

    def test_run_quality_checks(self):
        """Test running all quality checks."""
        results = self.checker.run_quality_checks(self.test_df, "test_table")
        
        self.assertEqual(results["table_name"], "test_table")
        self.assertIn("timestamp", results)
        self.assertIn("schema_validation", results)
        self.assertIn("completeness", results)
        self.assertIn("quality_checks", results)

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment."""
        cls.spark.stop()

if __name__ == '__main__':
    unittest.main() 