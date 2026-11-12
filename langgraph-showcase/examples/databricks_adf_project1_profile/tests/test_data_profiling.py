import unittest
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType
from src.data_profiling.profiler import DataProfiler

class TestDataProfiler(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test environment."""
        cls.spark = SparkSession.builder \
            .appName("TestDataProfiler") \
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
            (3, "Bob", 35, 88.5),
            (4, "Carol", 28, 90.0),
            (5, "Dave", 32, 87.5)
        ]
        cls.test_df = cls.spark.createDataFrame(cls.test_data, cls.test_schema)

    def setUp(self):
        """Set up test case."""
        self.profiler = DataProfiler()

    def test_profile_column_numeric(self):
        """Test profiling numeric column."""
        profile = self.profiler.profile_column(self.test_df, "age")
        
        self.assertEqual(profile["column_name"], "age")
        self.assertEqual(profile["data_type"], "IntegerType")
        self.assertEqual(profile["total_count"], 5)
        self.assertEqual(profile["null_count"], 0)
        self.assertEqual(profile["distinct_count"], 5)
        
        # Check numeric-specific metrics
        self.assertIn("mean", profile)
        self.assertIn("stddev", profile)
        self.assertIn("min", profile)
        self.assertIn("max", profile)
        self.assertIn("median", profile)
        self.assertIn("skewness", profile)
        self.assertIn("kurtosis", profile)

    def test_profile_column_string(self):
        """Test profiling string column."""
        profile = self.profiler.profile_column(self.test_df, "name")
        
        self.assertEqual(profile["column_name"], "name")
        self.assertEqual(profile["data_type"], "StringType")
        self.assertEqual(profile["total_count"], 5)
        self.assertEqual(profile["null_count"], 0)
        self.assertEqual(profile["distinct_count"], 5)
        
        # Check string-specific metrics
        self.assertIn("avg_length", profile)
        self.assertIn("min_length", profile)
        self.assertIn("max_length", profile)

    def test_profile_correlations(self):
        """Test correlation analysis."""
        correlations = self.profiler.profile_correlations(self.test_df)
        
        # Check if correlation matrix contains expected columns
        self.assertIn("age", correlations)
        self.assertIn("score", correlations)
        
        # Check if correlations are calculated
        self.assertIn("score", correlations["age"])
        self.assertIn("age", correlations["score"])

    def test_profile_dataframe(self):
        """Test complete DataFrame profiling."""
        profile = self.profiler.profile_dataframe(self.test_df, "test_table")
        
        self.assertEqual(profile["table_name"], "test_table")
        self.assertIn("timestamp", profile)
        self.assertEqual(profile["row_count"], 5)
        self.assertEqual(profile["column_count"], 4)
        
        # Check if all columns are profiled
        self.assertIn("id", profile["column_profiles"])
        self.assertIn("name", profile["column_profiles"])
        self.assertIn("age", profile["column_profiles"])
        self.assertIn("score", profile["column_profiles"])
        
        # Check if correlations are included
        self.assertIn("correlations", profile)

    def test_export_profile(self):
        """Test profile export functionality."""
        import tempfile
        import os
        
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            # Generate and export profile
            self.profiler.profile_dataframe(self.test_df, "test_table")
            self.profiler.export_profile("test_table", tmp_path)
            
            # Verify file exists and has content
            self.assertTrue(os.path.exists(tmp_path))
            self.assertGreater(os.path.getsize(tmp_path), 0)
            
        finally:
            # Clean up temporary file
            os.unlink(tmp_path)

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment."""
        cls.spark.stop()

if __name__ == '__main__':
    unittest.main() 