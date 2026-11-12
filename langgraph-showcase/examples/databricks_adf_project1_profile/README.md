# Databricks Data Quality & Profiling Template v1.0

This template provides a standardized approach for implementing data quality checks, data profiling, and ETL processes in Databricks using PySpark and Delta Lake.

## Project Structure

```
├── notebooks/                    # Databricks notebooks
│   ├── 01_data_quality/         # Data quality notebooks
│   ├── 02_data_profiling/       # Data profiling notebooks
│   └── 03_etl_jobs/            # ETL job notebooks
├── src/                         # Source code
│   ├── data_quality/           # Data quality modules
│   ├── data_profiling/         # Data profiling modules
│   ├── etl_jobs/              # ETL pipeline modules
│   │   ├── config/            # ETL configuration files
│   │   └── etl_pipeline.py    # Main ETL pipeline class
│   └── utils/                  # Utility functions
├── tests/                      # Test files
├── conf/                       # Configuration files
├── requirements.txt            # Python dependencies
└── databricks-requirements.txt # Databricks-specific requirements
```

## Features

- Data Quality Framework
  - Schema validation
  - Data completeness checks
  - Data type validation
  - Custom quality rules
  - Quality metrics tracking

- Data Profiling
  - Statistical analysis
  - Data distribution analysis
  - Column profiling
  - Correlation analysis
  - Data quality metrics

- ETL Pipeline
  - Bronze (Raw) to Silver (Processing) to Gold (Serving) architecture
  - Delta Lake integration
  - Configurable transformations
  - Custom aggregations
  - Metadata tracking
  - Error handling and logging

- Delta Lake Integration
  - Delta table management
  - Schema evolution
  - Time travel
  - ACID transactions

## Setup Instructions

1. Create a new Databricks workspace
2. Import this repository
3. Install required libraries:
   ```bash
   pip install -r requirements.txt
   ```

4. Configure your Databricks cluster with the following settings:
   - Runtime: Databricks Runtime 12.2 LTS or later
   - Python Version: 3.9+
   - Libraries:
     - delta-spark
     - pyspark
     - pytest
     - great-expectations
     - pandas-profiling

5. Configure mount points for ETL:
   ```python
   # Example mount configuration
   dbutils.fs.mount(
     source = "wasbs://container@storage.blob.core.windows.net",
     mount_point = "/mnt/raw",
     extra_configs = {"fs.azure.account.key.storage.blob.core.windows.net": "YOUR_KEY"}
   )
   ```

## Usage

1. Data Quality Checks:
   ```python
   from src.data_quality.quality_checker import DataQualityChecker
   
   checker = DataQualityChecker()
   results = checker.run_quality_checks(df, "table_name")
   ```

2. Data Profiling:
   ```python
   from src.data_profiling.profiler import DataProfiler
   
   profiler = DataProfiler()
   profile = profiler.profile_dataframe(df)
   ```

3. ETL Pipeline:
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

   For detailed ETL configuration and usage, see [ETL Pipeline Documentation](src/etl_jobs/README.md)

## Data Layers (ETL)

### Bronze Layer (Raw)
- Location: `/mnt/raw/{table_name}`
- Format: Delta Lake
- Contains: Raw JSON data with ingestion metadata
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

## Testing

Run tests using pytest:
```bash
pytest tests/
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

MIT License 