# ETL Pipeline Documentation

This document provides detailed instructions on how to run and use the ETL pipeline for processing data from raw (bronze) to processing (silver) to serving (gold) layers in Azure Databricks.

## Overview

The ETL pipeline is designed to:
- Extract raw CSV data (SQL DW extracts) into bronze layer as Parquet
- Transform and process data in silver layer
- Create aggregated views in gold layer
- Support Delta Lake format throughout
- Provide configurable transformations and aggregations

## Prerequisites

1. Azure Databricks workspace
2. Access to source data in JSON format
3. Proper mount points configured for:
   - Raw data: `/mnt/raw`
   - Processing data: `/mnt/processing`
   - Serving data: `/mnt/serving`

## Configuration

The pipeline uses a JSON configuration file (`etl_config.json`) to define:
- Data paths
- Table configurations
- Transformations
- Aggregations

Example configuration:
```json
{
    "raw_path": "/mnt/raw",
    "processing_path": "/mnt/processing",
    "serving_path": "/mnt/serving",
    "tables": {
        "your_table": {
            "source_path": "/path/to/extracts/*.csv",
            "transformations": {
                "column_name": {
                    "type": "cast",
                    "target_type": "string"
                }
            },
            "aggregations": {
                "summary_name": {
                    "group_by": ["column1", "column2"],
                    "aggregations": {
                        "metric1": "sum(column3)",
                        "metric2": "count(*)"
                    }
                }
            }
        }
    }
}
```

## Running the Pipeline

### 1. Using Databricks Notebook

1. Open the `RunETLPipeline.py` notebook in Databricks
2. Update the config path:
```python
config_path = "/Workspace/Repos/your-repo/src/etl_jobs/config/etl_config.json"
```

3. Run the notebook cells in sequence

### 2. Using Python Code

```python
from src.etl_jobs.etl_pipeline import ETLPipeline

# Initialize pipeline
etl = ETLPipeline("path/to/etl_config.json")

# Run pipeline for a specific table
etl.run_pipeline(
    table_name="your_table",
    source_path="path/to/source",
    transformations=transformations,
    aggregations=aggregations
)
```

## Data Layers

### Bronze Layer (Raw)
- Location: `/mnt/raw/{table_name}`
- Format: Parquet
- Contains: Raw CSV extracts with ingestion metadata
- Metadata columns:
  - `_ingestion_timestamp`
  - `_source_file`

### Silver Layer (Processing)
- Location: `/mnt/processing/{table_name}`
- Format: Delta Lake
- Contains: Transformed and cleaned data
- Metadata columns:
  - `_processing_timestamp`

### Gold Layer (Serving)
- Location: `/mnt/serving/{table_name}`
- Format: Delta Lake
- Contains: Aggregated data ready for consumption
- Metadata columns:
  - `_serving_timestamp`

## Available Transformations

1. Type Casting:
```json
{
    "column_name": {
        "type": "cast",
        "target_type": "string|integer|decimal(10,2)"
    }
}
```

2. Timestamp Conversion:
```json
{
    "column_name": {
        "type": "timestamp",
        "format": "yyyy-MM-dd HH:mm:ss"
    }
}
```

## Available Aggregations

Configure aggregations in the config file:
```json
"aggregations": {
    "summary_name": {
        "group_by": ["column1", "column2"],
        "aggregations": {
            "metric1": "sum(column3)",
            "metric2": "count(*)"
        }
    }
}
```

## Accessing the Data

### Using SQL Views
```sql
-- Create view
CREATE OR REPLACE VIEW your_table_summary AS
SELECT *
FROM delta.`/mnt/serving/your_table`

-- Query view
SELECT *
FROM your_table_summary
WHERE condition
```

### Using Delta Tables Directly
```python
# Read from any layer
df_bronze = spark.read.format("parquet").load("/mnt/raw/your_table")
df_silver = spark.read.format("delta").load("/mnt/processing/your_table")
df_gold = spark.read.format("delta").load("/mnt/serving/your_table")
```

## Error Handling

The pipeline includes comprehensive error handling:
- Logs all operations
- Captures and reports errors
- Maintains data integrity across layers

## Best Practices

1. Always validate your configuration file before running
2. Monitor the logs for any issues
3. Use appropriate data types in transformations
4. Test aggregations with sample data first
5. Keep your Delta tables optimized

## Troubleshooting

Common issues and solutions:

1. **Mount Point Issues**
   - Verify mount points are correctly configured
   - Check permissions on mounted storage

2. **Schema Evolution**
   - Use `mergeSchema` option when writing Delta tables
   - Handle schema changes in transformations

3. **Performance Issues**
   - Optimize your Delta tables regularly
   - Use appropriate partition columns
   - Monitor cluster resources

## Support

For issues or questions:
1. Check the logs in Databricks
2. Review the configuration
3. Verify data formats and paths
4. Contact your Databricks administrator 