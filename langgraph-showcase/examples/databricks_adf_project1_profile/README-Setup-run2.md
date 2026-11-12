# Databricks Project Setup and Running Guide

This guide provides step-by-step instructions for setting up and running the Databricks project template for data quality and profiling.

## Prerequisites

1. **Databricks Workspace Access**
   - Access to a Databricks workspace
   - Appropriate permissions to create clusters and run jobs
   - Access to DBFS (Databricks File System)

2. **Required Software**
   - Python 3.9 or later
   - Git for version control
   - Databricks CLI (optional, for local development)

## Project Structure

```
project_root/
├── src/
│   ├── data_quality/
│   │   └── quality_checker.py
│   ├── data_profiling/
│   │   └── profiler.py
│   └── etl_jobs/
│       └── etl_pipeline.py
├── tests/
│   ├── test_data_quality.py
│   ├── test_data_profiling.py
│   └── test_etl_pipeline.py
├── notebooks/
│   ├── 01_data_quality/
│   │   └── DataQualityChecks.py
│   ├── 02_data_profiling/
│   │   └── DataProfiling.py
│   └── 03_etl_jobs/
│       └── RunETLPipeline.py
├── requirements.txt
└── databricks-requirements.txt
```

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <repository-url>
cd <project-directory>
```

### 2. Configure Databricks Workspace

1. **Create a New Cluster**:
   - Go to Clusters in your Databricks workspace
   - Click "Create Cluster"
   - Configure with the following settings:
     - Runtime: Databricks Runtime 12.2 LTS or later
     - Python Version: 3.9+
     - Worker Type: Choose based on your needs
     - Min Workers: 1
     - Max Workers: Auto

2. **Install Dependencies**:
   - In your cluster configuration, go to "Libraries"
   - Click "Install New"
   - Choose "Upload Python Egg or PyPI"
   - Upload the `requirements.txt` file
   - Click "Install"

### 3. Import Project Files

1. **Import Notebooks**:
   - Go to Workspace in your Databricks workspace
   - Create a new folder for your project
   - Import the notebooks from the `notebooks/` directory
   - Maintain the folder structure as shown above

2. **Upload Source Code**:
   - Create a Repo in your Databricks workspace
   - Upload the contents of the `src/` directory
   - Ensure the Python path is correctly set

## Running the Project

### 1. Data Quality Checks

1. **Open DataQualityChecks Notebook**:
   ```python
   # Navigate to notebooks/01_data_quality/DataQualityChecks.py
   ```

2. **Configure Parameters**:
   - Set the target table path
   - Define quality rules
   - Configure output locations

3. **Run the Notebook**:
   - Select your configured cluster
   - Run all cells
   - Review the quality check results

### 2. Data Profiling

1. **Open DataProfiling Notebook**:
   ```python
   # Navigate to notebooks/02_data_profiling/DataProfiling.py
   ```

2. **Set Up Profiling**:
   - Specify the data source
   - Configure profiling parameters
   - Set output locations

3. **Execute Profiling**:
   - Run all cells
   - Review the profiling results
   - Export profiles if needed

### 3. ETL Pipeline

1. **Open RunETLPipeline Notebook**:
   ```python
   # Navigate to notebooks/03_etl_jobs/RunETLPipeline.py
   ```

2. **Configure Pipeline**:
   - Set source and target paths
   - Define transformations
   - Configure aggregations

3. **Run the Pipeline**:
   - Execute all cells
   - Monitor the progress
   - Verify the results

## Running Tests

### 1. Unit Tests

```bash
# Run all unit tests
python -m unittest discover tests/

# Run specific test file
python -m unittest tests/test_etl_pipeline.py
```

### 2. UAT Tests

```bash
# Run UAT tests
python -m unittest tests/test_etl_pipeline.py TestETLPipelineUAT
```

## Monitoring and Maintenance

### 1. Logs and Monitoring

- Check Databricks cluster logs for errors
- Monitor job runs in the Jobs section
- Review quality check results in Delta tables
- Check profiling results in the specified output location

### 2. Common Issues and Solutions

1. **Cluster Issues**:
   - Verify cluster configuration
   - Check library installations
   - Monitor resource usage

2. **Data Quality Failures**:
   - Review quality rules
   - Check data source
   - Verify transformations

3. **Performance Issues**:
   - Optimize cluster configuration
   - Review data partitioning
   - Check for resource bottlenecks

## Best Practices

1. **Development**:
   - Use version control
   - Follow coding standards
   - Write comprehensive tests
   - Document changes

2. **Deployment**:
   - Test in development first
   - Use staging environment
   - Monitor production runs
   - Maintain backup configurations

3. **Maintenance**:
   - Regular dependency updates
   - Performance monitoring
   - Log rotation
   - Regular testing

## Support and Resources

- Databricks Documentation: [docs.databricks.com](https://docs.databricks.com)
- Project Wiki: [link-to-wiki]
- Issue Tracker: [link-to-issues]
- Support Contact: [support-email]

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request

## License

[Specify your license here] 