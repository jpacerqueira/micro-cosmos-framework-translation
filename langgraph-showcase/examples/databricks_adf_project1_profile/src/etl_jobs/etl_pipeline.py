from typing import Dict, Optional
from pyspark.sql import SparkSession
from pyspark.sql.functions import current_timestamp, col, to_timestamp, input_file_name
from datetime import datetime
import logging
from src.data_quality.quality_checker import DataQualityChecker
from src.data_profiling.profiler import DataProfiler

class ETLPipeline:
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the ETL pipeline with configuration.
        
        Args:
            config_path: Path to JSON configuration file
        """
        self.spark = SparkSession.builder \
            .appName("ETLPipeline") \
            .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
            .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
            .getOrCreate()
        
        self.logger = logging.getLogger(__name__)
        self.config = self._load_config(config_path) if config_path else {}
        
        # Set up paths
        self.raw_path = self.config.get("raw_path", "/mnt/raw")
        self.processing_path = self.config.get("processing_path", "/mnt/processing")
        self.serving_path = self.config.get("serving_path", "/mnt/serving")
        
        # Initialize quality checker and profiler
        self.quality_checker = DataQualityChecker()
        self.profiler = DataProfiler()

    def _read_delta_as_of(self, path: str, *, version: Optional[int] = None, timestamp: Optional[str] = None):
        """
        Read a Delta table with time travel.

        Args:
            path: Delta table path
            version: Delta version to read (mutually exclusive with timestamp)
            timestamp: Timestamp string for time travel (mutually exclusive with version)
        """
        if version is not None and timestamp is not None:
            raise ValueError("Provide only one of version or timestamp for Delta time travel")

        reader = self.spark.read.format("delta")
        if version is not None:
            reader = reader.option("versionAsOf", int(version))
        if timestamp is not None:
            reader = reader.option("timestampAsOf", timestamp)

        return reader.load(path)

    def _load_config(self, config_path: str) -> Dict:
        """Load configuration from JSON file."""
        import json
        with open(config_path, 'r') as f:
            return json.load(f)

    def extract_raw_data(self, source_path: str, table_name: str) -> None:
        """
        Extract raw CSV data (SQL DW extracts) into bronze layer as Parquet.
        
        Args:
            source_path: Path/glob to source CSV files
            table_name: Name of the table to create
        """
        try:
            # Read CSV data
            df = (
                self.spark.read
                .option("header", "true")
                .option("inferSchema", "true")
                .csv(source_path)
            )
            
            # Add metadata columns
            df = df.withColumn("_ingestion_timestamp", current_timestamp()) \
                 .withColumn("_source_file", input_file_name())
            
            # Write to bronze layer
            bronze_path = f"{self.raw_path}/{table_name}"
            df.write.format("parquet") \
                .mode("append") \
                .save(bronze_path)
            
            self.logger.info(f"Successfully extracted raw data to {bronze_path}")
            
        except Exception as e:
            self.logger.error(f"Error extracting raw data: {str(e)}")
            raise

    def _run_quality_and_profiling(self, df, table_name: str) -> bool:
        """
        Run data quality checks and profiling on the dataframe.
        
        Args:
            df: Spark DataFrame to check
            table_name: Name of the table being processed
            
        Returns:
            bool: True if all quality checks pass, False otherwise
        """
        try:
            # Run data quality checks
            quality_results = self.quality_checker.run_quality_checks(df, table_name)
            
            # Run data profiling
            profile_results = self.profiler.profile_dataframe(df)
            
            # Log quality check results
            self.logger.info(f"Quality check results for {table_name}:")
            for check, result in quality_results.items():
                self.logger.info(f"  {check}: {result}")
            
            # Log profiling results
            self.logger.info(f"Profiling results for {table_name}:")
            for metric, value in profile_results.items():
                self.logger.info(f"  {metric}: {value}")
            
            # Check if quality checks passed
            quality_passed = all(result.get('passed', False) for result in quality_results.values())
            
            if not quality_passed:
                self.logger.warning(f"Quality checks failed for {table_name}")
                return False
                
            return True
            
        except Exception as e:
            self.logger.error(f"Error in quality and profiling checks: {str(e)}")
            raise

    def process_data(self, table_name: str, transformations: Dict) -> None:
        """
        Process bronze data into silver layer with transformations.
        Includes data quality and profiling checks.
        
        Args:
            table_name: Name of the table to process
            transformations: Dictionary of transformations to apply
        """
        try:
            # Read from bronze layer
            bronze_path = f"{self.raw_path}/{table_name}"
            df = self.spark.read.format("parquet").load(bronze_path)
            
            # Run quality and profiling checks
            if not self._run_quality_and_profiling(df, table_name):
                raise ValueError(f"Data quality checks failed for {table_name}")
            
            # Apply transformations
            for col_name, transform in transformations.items():
                if transform["type"] == "cast":
                    df = df.withColumn(col_name, col(col_name).cast(transform["target_type"]))
                elif transform["type"] == "timestamp":
                    df = df.withColumn(col_name, to_timestamp(col(col_name), transform["format"]))
                # Add more transformation types as needed
            
            # Add processing metadata
            df = df.withColumn("_processing_timestamp", current_timestamp())
            
            # Write to silver layer
            silver_path = f"{self.processing_path}/{table_name}"
            df.write.format("delta") \
                .mode("overwrite") \
                .option("mergeSchema", "true") \
                .save(silver_path)
            
            self.logger.info(f"Successfully processed data to {silver_path}")
            
        except Exception as e:
            self.logger.error(f"Error processing data: {str(e)}")
            raise

    def serve_data(self, table_name: str, aggregations: Optional[Dict] = None) -> None:
        """
        Create serving layer (gold) with aggregated/transformed data.
        
        Args:
            table_name: Name of the table to serve
            aggregations: Dictionary of aggregations to apply
        """
        try:
            # Read from silver layer
            silver_path = f"{self.processing_path}/{table_name}"
            df = self._read_delta_as_of(silver_path)
            
            # Apply aggregations if specified
            if aggregations:
                for agg_name, agg_config in aggregations.items():
                    group_cols = agg_config.get("group_by", [])
                    agg_exprs = agg_config.get("aggregations", {})
                    
                    df = df.groupBy(group_cols).agg(agg_exprs)
            
            # Add serving metadata
            df = df.withColumn("_serving_timestamp", current_timestamp())
            
            # Write to gold layer
            gold_path = f"{self.serving_path}/{table_name}"
            df.write.format("delta") \
                .mode("overwrite") \
                .option("mergeSchema", "true") \
                .save(gold_path)
            
            self.logger.info(f"Successfully served data to {gold_path}")
            
        except Exception as e:
            self.logger.error(f"Error serving data: {str(e)}")
            raise

    def run_pipeline(self, table_name: str, source_path: str, 
                    transformations: Dict, aggregations: Optional[Dict] = None) -> None:
        """
        Run the complete ETL pipeline for a table.
        
        Args:
            table_name: Name of the table to process
            source_path: Path to source JSON files
            transformations: Dictionary of transformations to apply
            aggregations: Optional dictionary of aggregations to apply
        """
        try:
            self.logger.info(f"Starting ETL pipeline for table: {table_name}")
            
            # Extract raw data
            self.extract_raw_data(source_path, table_name)
            
            # Process data (includes quality and profiling checks)
            self.process_data(table_name, transformations)
            
            # Serve data
            self.serve_data(table_name, aggregations)
            
            self.logger.info(f"Successfully completed ETL pipeline for table: {table_name}")
            
        except Exception as e:
            self.logger.error(f"Error in ETL pipeline: {str(e)}")
            raise
        finally:
            self.spark.stop() 

    def create_gold_view(
        self,
        table_name: str,
        *,
        view_name: Optional[str] = None,
        version: Optional[int] = None,
        timestamp: Optional[str] = None
    ) -> str:
        """
        Create or replace a Spark SQL temp view over the Gold (serving) tier.

        This enables SQL queries directly over Gold, including time travel windows via
        Delta "AS OF" semantics (versionAsOf/timestampAsOf options).
        """
        gold_path = f"{self.serving_path}/{table_name}"
        df = self._read_delta_as_of(gold_path, version=version, timestamp=timestamp)
        resolved_view_name = view_name or f"{table_name}_gold"
        df.createOrReplaceTempView(resolved_view_name)
        return resolved_view_name