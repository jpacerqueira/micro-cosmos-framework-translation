# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # Data Quality Checks
# MAGIC 
# MAGIC This notebook demonstrates how to use the data quality framework to validate and check data quality in Delta tables.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC 
# MAGIC First, let's import the necessary modules and initialize our data quality checker.

# COMMAND ----------

from src.data_quality.quality_checker import DataQualityChecker
from pyspark.sql import SparkSession

# Initialize Spark session
spark = SparkSession.builder.getOrCreate()

# Initialize data quality checker
checker = DataQualityChecker()

# COMMAND ----------

# MAGIC %md
# MAGIC ## Load Sample Data
# MAGIC 
# MAGIC Let's load a sample Delta table for demonstration purposes.

# COMMAND ----------

# Read sample data
df = spark.read.format("delta").load("/path/to/your/delta/table")

# Display sample data
display(df)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Define Quality Rules
# MAGIC 
# MAGIC Let's define some quality rules for our data.

# COMMAND ----------

quality_rules = {
    "id_not_null": {
        "type": "not_null",
        "column": "id"
    },
    "name_not_null": {
        "type": "not_null",
        "column": "name"
    },
    "age_range": {
        "type": "value_range",
        "column": "age",
        "min": 0,
        "max": 120
    },
    "score_range": {
        "type": "value_range",
        "column": "score",
        "min": 0,
        "max": 100
    }
}

# COMMAND ----------

# MAGIC %md
# MAGIC ## Run Quality Checks
# MAGIC 
# MAGIC Now, let's run the quality checks on our data.

# COMMAND ----------

# Run quality checks
results = checker.run_quality_checks(df, "sample_table")

# Display results
display(results)

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analyze Results
# MAGIC 
# MAGIC Let's analyze the quality check results and take appropriate actions.

# COMMAND ----------

# Check schema validation
schema_validation = results["schema_validation"]
if not schema_validation["schema_match"]:
    print("Schema validation failed!")
    print("Missing columns:", schema_validation["missing_columns"])
    print("Extra columns:", schema_validation["extra_columns"])
    print("Type mismatches:", schema_validation["type_mismatches"])
else:
    print("Schema validation passed!")

# COMMAND ----------

# Check completeness
completeness = results["completeness"]
for column, metrics in completeness.items():
    print(f"\nColumn: {column}")
    print(f"Total count: {metrics['total_count']}")
    print(f"Null count: {metrics['null_count']}")
    print(f"Completeness ratio: {metrics['completeness_ratio']:.2%}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Store Results
# MAGIC 
# MAGIC Let's store the quality check results for future reference.

# COMMAND ----------

# Convert results to DataFrame
results_df = spark.createDataFrame([(str(results),)], ["quality_check_results"])

# Write results to Delta table
results_df.write.format("delta").mode("append").saveAsTable("quality_check_results")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Quality Dashboard
# MAGIC 
# MAGIC Let's create a simple dashboard to visualize the quality metrics.

# COMMAND ----------

# Create quality metrics visualization
import matplotlib.pyplot as plt
import pandas as pd

# Convert completeness metrics to pandas DataFrame
completeness_df = pd.DataFrame([
    {
        "column": col,
        "completeness": metrics["completeness_ratio"]
    }
    for col, metrics in completeness.items()
])

# Create bar chart
plt.figure(figsize=(10, 6))
plt.bar(completeness_df["column"], completeness_df["completeness"])
plt.title("Data Completeness by Column")
plt.xlabel("Column")
plt.ylabel("Completeness Ratio")
plt.xticks(rotation=45)
plt.tight_layout()

# Display plot
display(plt.gcf()) 