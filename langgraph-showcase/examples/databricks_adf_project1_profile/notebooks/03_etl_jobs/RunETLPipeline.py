# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # ETL Pipeline Execution
# MAGIC 
# MAGIC This notebook demonstrates how to run the ETL pipeline with runtime parameters and proper error handling.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup Parameters
# MAGIC 
# MAGIC Define the parameters that can be set at runtime:

# COMMAND ----------

dbutils.widgets.text("config_path", "/Workspace/Repos/your-repo/src/etl_jobs/config/etl_config.json", "Config Path")
dbutils.widgets.text("table_name", "", "Table Name")
dbutils.widgets.text("source_path", "", "Source Path")
dbutils.widgets.dropdown("run_mode", "full", ["full", "extract", "process", "serve"], "Run Mode")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Import Required Modules

# COMMAND ----------

from src.etl_jobs.etl_pipeline import ETLPipeline
import json
from pyspark.sql import SparkSession
import logging

# COMMAND ----------

# MAGIC %md
# MAGIC ## Initialize Pipeline

# COMMAND ----------

# Get parameters
config_path = dbutils.widgets.get("config_path")
table_name = dbutils.widgets.get("table_name")
source_path = dbutils.widgets.get("source_path")
run_mode = dbutils.widgets.get("run_mode")

# Initialize logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize ETL pipeline
try:
    etl = ETLPipeline(config_path)
    logger.info("Successfully initialized ETL pipeline")
except Exception as e:
    logger.error(f"Failed to initialize ETL pipeline: {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Configuration

# COMMAND ----------

try:
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    if table_name not in config.get("tables", {}):
        raise ValueError(f"Table {table_name} not found in configuration")
    
    table_config = config["tables"][table_name]
    logger.info(f"Successfully loaded configuration for table: {table_name}")
except Exception as e:
    logger.error(f"Failed to load configuration: {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Pipeline

# COMMAND ----------

try:
    if run_mode == "full":
        # Run complete pipeline
        etl.run_pipeline(
            table_name=table_name,
            source_path=source_path or table_config["source_path"],
            transformations=table_config["transformations"],
            aggregations=table_config.get("aggregations")
        )
    elif run_mode == "extract":
        # Run only extraction
        etl.extract_raw_data(
            source_path=source_path or table_config["source_path"],
            table_name=table_name
        )
    elif run_mode == "process":
        # Run only processing
        etl.process_data(
            table_name=table_name,
            transformations=table_config["transformations"]
        )
    elif run_mode == "serve":
        # Run only serving
        etl.serve_data(
            table_name=table_name,
            aggregations=table_config.get("aggregations")
        )
    
    logger.info(f"Successfully completed {run_mode} mode for table: {table_name}")
except Exception as e:
    logger.error(f"Pipeline execution failed: {str(e)}")
    raise

# COMMAND ----------

# MAGIC %md
# MAGIC ## Verify Results

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check Bronze Layer (Raw Data)

# COMMAND ----------

try:
    bronze_df = spark.read.format("delta").load(f"{etl.raw_path}/{table_name}")
    display(bronze_df)
except Exception as e:
    logger.error(f"Failed to read bronze layer: {str(e)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check Silver Layer (Processed Data)

# COMMAND ----------

try:
    silver_df = spark.read.format("delta").load(f"{etl.processing_path}/{table_name}")
    display(silver_df)
except Exception as e:
    logger.error(f"Failed to read silver layer: {str(e)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ### Check Gold Layer (Serving Data)

# COMMAND ----------

try:
    gold_df = spark.read.format("delta").load(f"{etl.serving_path}/{table_name}")
    display(gold_df)
except Exception as e:
    logger.error(f"Failed to read gold layer: {str(e)}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create SQL Views

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Create view for the serving layer
# MAGIC CREATE OR REPLACE VIEW ${table_name}_serving AS
# MAGIC SELECT *
# MAGIC FROM delta.`${etl.serving_path}/${table_name}`

# COMMAND ----------

# MAGIC %md
# MAGIC ## Example Queries

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Example query to verify the data
# MAGIC SELECT *
# MAGIC FROM ${table_name}_serving
# MAGIC LIMIT 10

# COMMAND ----------

# MAGIC %md
# MAGIC ## Cleanup

# COMMAND ----------

# Remove widgets
dbutils.widgets.removeAll() 