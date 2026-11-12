# ETL Pipeline Runtime Notebook

This notebook provides a runtime interface for executing the ETL pipeline with configurable parameters and proper error handling.

## Overview

The `RunETLPipeline.py` notebook allows you to:
- Run the complete ETL pipeline or individual stages
- Configure pipeline parameters at runtime
- Monitor data quality and profiling results
- Verify data in each layer (Bronze, Silver, Gold)
- Create SQL views for easy data access

## Prerequisites

1. Access to a Databricks workspace
2. Proper mount points configured for:
   - Raw data: `/mnt/raw`
   - Processing data: `/mnt/processing`
   - Serving data: `/mnt/serving`
3. ETL configuration file (`etl_config.json`) in place
4. Required Python packages installed:
   - pyspark
   - delta-spark
   - logging

## Runtime Parameters

The notebook provides the following configurable parameters:

1. **Config Path** (`config_path`)
   - Type: Text input
   - Default: `/Workspace/Repos/your-repo/src/etl_jobs/config/etl_config.json`
   - Description: Path to the ETL configuration file

2. **Table Name** (`table_name`)
   - Type: Text input
   - Description: Name of the table to process (must exist in config)

3. **Source Path** (`source_path`)
   - Type: Text input
   - Description: Optional override for source data path

4. **Run Mode** (`run_mode`)
   - Type: Dropdown
   - Options:
     - `full`: Run complete pipeline
     - `extract`: Only extract to bronze layer
     - `process`: Only process to silver layer
     - `serve`: Only serve to gold layer
   - Default: `full`

## Usage

1. **Open the Notebook**:
   - Navigate to `notebooks/03_etl_jobs/RunETLPipeline.py`
   - Ensure you have the required permissions

2. **Set Parameters**:
   - Fill in the required parameters in the widgets
   - Verify the configuration path is correct
   - Select the appropriate run mode

3. **Run the Pipeline**:
   - Execute the notebook cells in sequence
   - Monitor the logs for progress and any issues
   - Check the verification steps for each layer

4. **Verify Results**:
   - Review data in each layer (Bronze, Silver, Gold)
   - Check the created SQL views
   - Run example queries to validate the data

## Pipeline Stages

### 1. Extraction (Bronze Layer)
- Reads raw JSON data
- Adds ingestion metadata
- Stores in Delta format
- Path: `/mnt/raw/{table_name}`

### 2. Processing (Silver Layer)
- Applies data quality checks
- Runs data profiling
- Performs transformations
- Path: `/mnt/processing/{table_name}`

### 3. Serving (Gold Layer)
- Creates aggregated views
- Optimizes for query performance
- Path: `/mnt/serving/{table_name}`

## Error Handling

The notebook includes comprehensive error handling:
- Validates configuration before execution
- Checks for required parameters
- Logs all operations and errors
- Provides detailed error messages
- Maintains data integrity across layers

## Monitoring

Monitor the pipeline execution through:
1. **Logs**:
   - Operation status
   - Error messages
   - Quality check results
   - Profiling metrics

2. **Data Verification**:
   - Sample data display
   - Record counts
   - Schema validation
   - Data quality metrics

## SQL Views

The notebook automatically creates SQL views:
- Name format: `{table_name}_serving`
- Provides easy access to serving layer data
- Can be used for analysis and reporting

## Example Queries

```sql
-- View serving layer data
SELECT *
FROM ${table_name}_serving
LIMIT 10

-- Check data quality metrics
SELECT *
FROM delta.`/mnt/processing/${table_name}`
WHERE _quality_check_passed = false
```

## Troubleshooting

Common issues and solutions:

1. **Configuration Errors**
   - Verify config file path
   - Check JSON syntax
   - Ensure table exists in config

2. **Data Quality Failures**
   - Review quality check results
   - Check data completeness
   - Verify data types

3. **Performance Issues**
   - Monitor cluster resources
   - Check partition strategy
   - Review transformation complexity

## Best Practices

1. Always validate parameters before running
2. Monitor logs for any warnings or errors
3. Verify data in each layer after processing
4. Use appropriate run mode for your needs
5. Clean up temporary views when done

## Support

For issues or questions:
1. Check the logs in Databricks
2. Review the configuration
3. Verify data formats and paths
4. Contact your Databricks administrator 