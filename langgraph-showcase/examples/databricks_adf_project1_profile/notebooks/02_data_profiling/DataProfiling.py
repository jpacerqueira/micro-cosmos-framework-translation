# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # Data Profiling
# MAGIC 
# MAGIC This notebook demonstrates how to use the data profiling framework to analyze and understand your data.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Setup
# MAGIC 
# MAGIC First, let's import the necessary modules and initialize our data profiler.

# COMMAND ----------

from src.data_profiling.profiler import DataProfiler
from pyspark.sql import SparkSession

# Initialize Spark session
spark = SparkSession.builder.getOrCreate()

# Initialize data profiler
profiler = DataProfiler()

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
# MAGIC ## Generate Data Profile
# MAGIC 
# MAGIC Let's generate a comprehensive profile of our data.

# COMMAND ----------

# Generate profile
profile = profiler.profile_dataframe(df, "sample_table")

# Display profile summary
print(f"Table: {profile['table_name']}")
print(f"Timestamp: {profile['timestamp']}")
print(f"Row count: {profile['row_count']}")
print(f"Column count: {profile['column_count']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analyze Column Profiles
# MAGIC 
# MAGIC Let's analyze the profile of each column in detail.

# COMMAND ----------

# Display column profiles
for column, metrics in profile["column_profiles"].items():
    print(f"\nColumn: {column}")
    print(f"Data type: {metrics['data_type']}")
    print(f"Total count: {metrics['total_count']}")
    print(f"Null count: {metrics['null_count']}")
    print(f"Distinct count: {metrics['distinct_count']}")
    
    # Display type-specific metrics
    if "mean" in metrics:
        print("\nNumeric metrics:")
        print(f"Mean: {metrics['mean']:.2f}")
        print(f"StdDev: {metrics['stddev']:.2f}")
        print(f"Min: {metrics['min']}")
        print(f"Max: {metrics['max']}")
        print(f"Median: {metrics['median']}")
        print(f"Skewness: {metrics['skewness']:.2f}")
        print(f"Kurtosis: {metrics['kurtosis']:.2f}")
    
    if "avg_length" in metrics:
        print("\nString metrics:")
        print(f"Average length: {metrics['avg_length']:.2f}")
        print(f"Min length: {metrics['min_length']}")
        print(f"Max length: {metrics['max_length']}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Analyze Correlations
# MAGIC 
# MAGIC Let's analyze the correlations between numeric columns.

# COMMAND ----------

# Display correlation matrix
correlations = profile["correlations"]
print("\nCorrelation Matrix:")
for col1 in correlations:
    print(f"\n{col1}:")
    for col2, corr_value in correlations[col1].items():
        print(f"  {col2}: {corr_value:.2f}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Visualize Correlations
# MAGIC 
# MAGIC Let's create a heatmap to visualize the correlations.

# COMMAND ----------

import seaborn as sns
import pandas as pd
import numpy as np

# Convert correlation matrix to pandas DataFrame
corr_matrix = pd.DataFrame(correlations)

# Create heatmap
plt.figure(figsize=(10, 8))
sns.heatmap(corr_matrix, annot=True, cmap="coolwarm", center=0)
plt.title("Correlation Heatmap")
plt.tight_layout()

# Display plot
display(plt.gcf())

# COMMAND ----------

# MAGIC %md
# MAGIC ## Store Profile Results
# MAGIC 
# MAGIC Let's store the profiling results for future reference.

# COMMAND ----------

# Convert profile to DataFrame
profile_df = spark.createDataFrame([(str(profile),)], ["profile_results"])

# Write results to Delta table
profile_df.write.format("delta").mode("append").saveAsTable("data_profiling_results")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Export Profile
# MAGIC 
# MAGIC Let's export the profile to a JSON file for external use.

# COMMAND ----------

# Export profile to JSON
profiler.export_profile("sample_table", "/dbfs/FileStore/profiles/sample_table_profile.json")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Create Profiling Dashboard
# MAGIC 
# MAGIC Let's create a simple dashboard to visualize key profiling metrics.

# COMMAND ----------

# Create profiling metrics visualization
import matplotlib.pyplot as plt

# Create subplots
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

# Plot 1: Null values by column
null_counts = pd.DataFrame([
    {
        "column": col,
        "null_count": metrics["null_count"]
    }
    for col, metrics in profile["column_profiles"].items()
])

ax1.bar(null_counts["column"], null_counts["null_count"])
ax1.set_title("Null Values by Column")
ax1.set_xlabel("Column")
ax1.set_ylabel("Null Count")
ax1.tick_params(axis='x', rotation=45)

# Plot 2: Distinct values by column
distinct_counts = pd.DataFrame([
    {
        "column": col,
        "distinct_count": metrics["distinct_count"]
    }
    for col, metrics in profile["column_profiles"].items()
])

ax2.bar(distinct_counts["column"], distinct_counts["distinct_count"])
ax2.set_title("Distinct Values by Column")
ax2.set_xlabel("Column")
ax2.set_ylabel("Distinct Count")
ax2.tick_params(axis='x', rotation=45)

plt.tight_layout()

# Display plots
display(plt.gcf()) 