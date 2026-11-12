import unittest
from unittest.mock import Mock, patch, MagicMock
from pyspark.sql import SparkSession
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType
from datetime import datetime
import json
import os
import tempfile
from src.etl_jobs.etl_pipeline import ETLPipeline

class TestETLPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        """Set up test environment before running tests."""
        # Create a test Spark session
        cls.spark = SparkSession.builder \
            .appName("ETLPipelineTest") \
            .master("local[2]") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
            .getOrCreate()
        
        # Create test data schema
        cls.test_schema = StructType([
            StructField("id", StringType(), True),
            StructField("name", StringType(), True),
            StructField("value", IntegerType(), True),
            StructField("timestamp", TimestampType(), True)
        ])
        
        # Create test data
        cls.test_data = [
            ("1", "test1", 100, datetime.now()),
            ("2", "test2", 200, datetime.now()),
            ("3", "test3", 300, datetime.now())
        ]
        
        # Create test DataFrame
        cls.test_df = cls.spark.createDataFrame(cls.test_data, cls.test_schema)
        
        # Create temporary directory for test files
        cls.temp_dir = tempfile.mkdtemp()
        
        # Create test configuration
        cls.test_config = {
            "raw_path": f"{cls.temp_dir}/raw",
            "processing_path": f"{cls.temp_dir}/processing",
            "serving_path": f"{cls.temp_dir}/serving",
            "tables": {
                "test_table": {
                    "source_path": f"{cls.temp_dir}/source",
                    "transformations": {
                        "value": {"type": "cast", "target_type": "integer"},
                        "timestamp": {"type": "timestamp", "format": "yyyy-MM-dd HH:mm:ss"}
                    },
                    "aggregations": {
                        "daily_summary": {
                            "group_by": ["name"],
                            "aggregations": {
                                "total_value": "sum(value)",
                                "count": "count(*)"
                            }
                        }
                    }
                }
            }
        }
        
        # Write test configuration to file
        cls.config_path = f"{cls.temp_dir}/test_config.json"
        with open(cls.config_path, 'w') as f:
            json.dump(cls.test_config, f)

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment after running tests."""
        cls.spark.stop()
        # Clean up temporary directory
        import shutil
        shutil.rmtree(cls.temp_dir)

    def setUp(self):
        """Set up test fixtures before each test method."""
        self.pipeline = ETLPipeline(self.config_path)
        
        # Create test directories
        os.makedirs(f"{self.temp_dir}/raw", exist_ok=True)
        os.makedirs(f"{self.temp_dir}/processing", exist_ok=True)
        os.makedirs(f"{self.temp_dir}/serving", exist_ok=True)
        os.makedirs(f"{self.temp_dir}/source", exist_ok=True)

    def tearDown(self):
        """Clean up test fixtures after each test method."""
        self.pipeline.spark.stop()

    def test_init(self):
        """Test ETLPipeline initialization."""
        self.assertIsNotNone(self.pipeline)
        self.assertIsNotNone(self.pipeline.spark)
        self.assertIsNotNone(self.pipeline.config)
        self.assertEqual(self.pipeline.raw_path, self.test_config["raw_path"])
        self.assertEqual(self.pipeline.processing_path, self.test_config["processing_path"])
        self.assertEqual(self.pipeline.serving_path, self.test_config["serving_path"])

    def test_load_config(self):
        """Test configuration loading."""
        config = self.pipeline._load_config(self.config_path)
        self.assertEqual(config, self.test_config)

    @patch('src.etl_jobs.etl_pipeline.ETLPipeline._run_quality_and_profiling')
    def test_extract_raw_data(self, mock_quality_check):
        """Test raw data extraction."""
        # Mock quality check to pass
        mock_quality_check.return_value = True
        
        # Write test data to CSV extract (directory)
        test_csv_path = f"{self.temp_dir}/source/test_data_csv"
        self.test_df.write.mode("overwrite").option("header", "true").csv(test_csv_path)
        
        # Extract raw data
        self.pipeline.extract_raw_data(test_csv_path, "test_table")
        
        # Verify data was written to raw layer
        raw_df = self.spark.read.format("parquet").load(f"{self.pipeline.raw_path}/test_table")
        self.assertEqual(raw_df.count(), len(self.test_data))
        self.assertTrue("_ingestion_timestamp" in raw_df.columns)
        self.assertTrue("_source_file" in raw_df.columns)

    @patch('src.etl_jobs.etl_pipeline.ETLPipeline._run_quality_and_profiling')
    def test_process_data(self, mock_quality_check):
        """Test data processing with transformations."""
        # Mock quality check to pass
        mock_quality_check.return_value = True
        
        # Write test data to raw layer
        raw_path = f"{self.pipeline.raw_path}/test_table"
        self.test_df.write.format("parquet").mode("append").save(raw_path)
        
        # Process data
        transformations = self.test_config["tables"]["test_table"]["transformations"]
        self.pipeline.process_data("test_table", transformations)
        
        # Verify processed data
        processed_df = self.spark.read.format("delta").load(f"{self.pipeline.processing_path}/test_table")
        self.assertEqual(processed_df.count(), len(self.test_data))
        self.assertTrue("_processing_timestamp" in processed_df.columns)
        self.assertEqual(processed_df.schema["value"].dataType, IntegerType())

    def test_serve_data(self):
        """Test data serving with aggregations."""
        # Write test data to processing layer
        processing_path = f"{self.pipeline.processing_path}/test_table"
        self.test_df.write.format("delta").mode("append").save(processing_path)
        
        # Serve data
        aggregations = self.test_config["tables"]["test_table"]["aggregations"]
        self.pipeline.serve_data("test_table", aggregations)
        
        # Verify served data
        served_df = self.spark.read.format("delta").load(f"{self.pipeline.serving_path}/test_table")
        self.assertTrue("_serving_timestamp" in served_df.columns)
        self.assertTrue("total_value" in served_df.columns)
        self.assertTrue("count" in served_df.columns)

    def test_run_pipeline(self):
        """Test complete pipeline execution."""
        # Write test data to source
        test_csv_path = f"{self.temp_dir}/source/test_data_csv_full"
        self.test_df.write.mode("overwrite").option("header", "true").csv(test_csv_path)
        
        # Run pipeline
        table_config = self.test_config["tables"]["test_table"]
        self.pipeline.run_pipeline(
            "test_table",
            test_csv_path,
            table_config["transformations"],
            table_config["aggregations"]
        )
        
        # Verify all layers
        raw_df = self.spark.read.format("parquet").load(f"{self.pipeline.raw_path}/test_table")
        processed_df = self.spark.read.format("delta").load(f"{self.pipeline.processing_path}/test_table")
        served_df = self.spark.read.format("delta").load(f"{self.pipeline.serving_path}/test_table")
        
        self.assertEqual(raw_df.count(), len(self.test_data))
        self.assertEqual(processed_df.count(), len(self.test_data))
        self.assertTrue(served_df.count() > 0)

    def test_quality_check_failure(self):
        """Test pipeline behavior when quality checks fail."""
        # Mock quality check to fail
        with patch('src.etl_jobs.etl_pipeline.ETLPipeline._run_quality_and_profiling', return_value=False):
            # Write test data to raw layer
            raw_path = f"{self.pipeline.raw_path}/test_table"
            self.test_df.write.format("parquet").mode("append").save(raw_path)
            
            # Attempt to process data
            with self.assertRaises(ValueError):
                self.pipeline.process_data("test_table", {})

    def test_error_handling(self):
        """Test error handling in pipeline operations."""
        # Test with invalid source path
        with self.assertRaises(Exception):
            self.pipeline.extract_raw_data("invalid_path", "test_table")
        
        # Test with invalid transformations
        with self.assertRaises(Exception):
            self.pipeline.process_data("test_table", {"invalid_column": {"type": "invalid_type"}})

class TestETLPipelineUAT(unittest.TestCase):
    """User Acceptance Testing scenarios for ETL Pipeline."""
    
    @classmethod
    def setUpClass(cls):
        """Set up UAT test environment."""
        cls.spark = SparkSession.builder \
            .appName("ETLPipelineUAT") \
            .master("local[2]") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
            .getOrCreate()
        
        # Create UAT test data
        cls.uat_data = [
            ("CUST001", "John Doe", 1000, datetime.now()),
            ("CUST002", "Jane Smith", 2000, datetime.now()),
            ("CUST003", "Bob Johnson", 3000, datetime.now())
        ]
        
        cls.uat_schema = StructType([
            StructField("customer_id", StringType(), True),
            StructField("customer_name", StringType(), True),
            StructField("transaction_amount", IntegerType(), True),
            StructField("transaction_date", TimestampType(), True)
        ])
        
        cls.uat_df = cls.spark.createDataFrame(cls.uat_data, cls.uat_schema)
        
        # Create UAT configuration
        cls.uat_config = {
            "raw_path": "/mnt/uat/raw",
            "processing_path": "/mnt/uat/processing",
            "serving_path": "/mnt/uat/serving",
            "tables": {
                "customer_transactions": {
                    "source_path": "/mnt/uat/source",
                    "transformations": {
                        "transaction_amount": {"type": "cast", "target_type": "decimal(10,2)"},
                        "transaction_date": {"type": "timestamp", "format": "yyyy-MM-dd HH:mm:ss"}
                    },
                    "aggregations": {
                        "daily_summary": {
                            "group_by": ["customer_id"],
                            "aggregations": {
                                "total_amount": "sum(transaction_amount)",
                                "transaction_count": "count(*)"
                            }
                        }
                    }
                }
            }
        }

    def test_uat_scenario_1(self):
        """UAT Scenario 1: End-to-end customer transaction processing."""
        pipeline = ETLPipeline()
        
        # Write UAT data
        uat_df = self.uat_df
        source_path = "/mnt/uat/source/customer_transactions_csv"
        uat_df.write.mode("overwrite").option("header", "true").csv(source_path)
        
        # Run pipeline
        table_config = self.uat_config["tables"]["customer_transactions"]
        pipeline.run_pipeline(
            "customer_transactions",
            source_path,
            table_config["transformations"],
            table_config["aggregations"]
        )
        
        # Verify results
        served_df = self.spark.read.format("delta").load("/mnt/uat/serving/customer_transactions")
        
        # Check aggregations
        self.assertTrue(served_df.count() > 0)
        self.assertTrue("total_amount" in served_df.columns)
        self.assertTrue("transaction_count" in served_df.columns)
        
        # Verify data quality
        self.assertTrue(served_df.filter("total_amount < 0").count() == 0)
        self.assertTrue(served_df.filter("transaction_count < 1").count() == 0)

    def test_uat_scenario_2(self):
        """UAT Scenario 2: Data quality and validation."""
        pipeline = ETLPipeline()
        
        # Create test data with quality issues
        problematic_data = [
            ("CUST001", "John Doe", -1000, datetime.now()),  # Negative amount
            ("CUST002", None, 2000, datetime.now()),         # Missing name
            ("CUST003", "Bob Johnson", 3000, None)           # Missing date
        ]
        problematic_df = self.spark.createDataFrame(problematic_data, self.uat_schema)
        
        # Write problematic data
        source_path = "/mnt/uat/source/problematic_transactions_csv"
        problematic_df.write.mode("overwrite").option("header", "true").csv(source_path)
        
        # Run pipeline and verify error handling
        table_config = self.uat_config["tables"]["customer_transactions"]
        with self.assertRaises(Exception):
            pipeline.run_pipeline(
                "customer_transactions",
                source_path,
                table_config["transformations"],
                table_config["aggregations"]
            )

    def test_uat_scenario_3(self):
        """UAT Scenario 3: Performance and scalability."""
        pipeline = ETLPipeline()
        
        # Create large dataset
        large_data = []
        for i in range(1000):
            large_data.append((
                f"CUST{i:04d}",
                f"Customer {i}",
                i * 100,
                datetime.now()
            ))
        
        large_df = self.spark.createDataFrame(large_data, self.uat_schema)
        
        # Write large dataset
        source_path = "/mnt/uat/source/large_transactions_csv"
        large_df.write.mode("overwrite").option("header", "true").csv(source_path)
        
        # Run pipeline and measure performance
        import time
        start_time = time.time()
        
        table_config = self.uat_config["tables"]["customer_transactions"]
        pipeline.run_pipeline(
            "customer_transactions",
            source_path,
            table_config["transformations"],
            table_config["aggregations"]
        )
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Verify performance
        self.assertLess(processing_time, 300)  # Should complete within 5 minutes
        
        # Verify results
        served_df = self.spark.read.format("delta").load("/mnt/uat/serving/customer_transactions")
        self.assertEqual(served_df.count(), 1000)  # All records processed

if __name__ == '__main__':
    unittest.main() 