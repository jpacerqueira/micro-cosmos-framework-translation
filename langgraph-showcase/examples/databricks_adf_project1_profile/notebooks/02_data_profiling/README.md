# Data Profiling Notebook

This notebook provides a comprehensive framework for analyzing and understanding your data through detailed profiling and visualization in Databricks.

## Overview

The `DataProfiling.py` notebook enables you to:
- Generate comprehensive data profiles
- Analyze column-level statistics
- Calculate correlations between variables
- Create visualizations and dashboards
- Store and export profiling results

## Prerequisites

1. Access to a Databricks workspace
2. Required Python packages:
   - pyspark
   - pandas
   - numpy
   - seaborn
   - matplotlib
3. Access to Delta tables for profiling
4. Proper permissions to create and write to profiling results table

## Components

### 1. Data Profiler
```python
from src.data_profiling.profiler import DataProfiler
profiler = DataProfiler()
```

### 2. Profile Generation
```python
profile = profiler.profile_dataframe(df, "sample_table")
```

## Usage

1. **Setup**:
   - Import required modules
   - Initialize Spark session
   - Create DataProfiler instance

2. **Load Data**:
   - Read Delta table
   - Verify data structure
   - Display sample data

3. **Generate Profile**:
   - Run profiling analysis
   - Review summary statistics
   - Analyze column profiles

4. **Analyze Results**:
   - Examine correlations
   - Create visualizations
   - Generate insights

5. **Store Results**:
   - Save profiling results
   - Export to JSON
   - Create dashboards

## Profile Analysis

### 1. Summary Statistics
```python
print(f"Table: {profile['table_name']}")
print(f"Timestamp: {profile['timestamp']}")
print(f"Row count: {profile['row_count']}")
print(f"Column count: {profile['column_count']}")
```

### 2. Column Profiles
```python
for column, metrics in profile["column_profiles"].items():
    print(f"\nColumn: {column}")
    print(f"Data type: {metrics['data_type']}")
    print(f"Total count: {metrics['total_count']}")
    print(f"Null count: {metrics['null_count']}")
    print(f"Distinct count: {metrics['distinct_count']}")
```

## Metrics Available

### 1. Numeric Columns
- Mean, Median, Mode
- Standard Deviation
- Min/Max values
- Skewness and Kurtosis
- Quartiles

### 2. String Columns
- Average length
- Min/Max length
- Distinct count
- Pattern analysis
- Value distribution

### 3. Correlation Analysis
- Pearson correlation
- Correlation matrix
- Correlation heatmap
- Feature relationships

## Visualizations

The notebook creates various visualizations:

1. **Correlation Heatmap**:
   - Shows relationships between numeric columns
   - Color-coded correlation strength
   - Interactive exploration

2. **Null Values Analysis**:
   - Bar chart of null counts
   - Column-wise null distribution
   - Completeness overview

3. **Distinct Values Analysis**:
   - Bar chart of distinct counts
   - Cardinality analysis
   - Value distribution

## Results Storage

Profiling results are stored in multiple formats:

1. **Delta Table**:
```python
profile_df = spark.createDataFrame([(str(profile),)], ["profile_results"])
profile_df.write.format("delta").mode("append").saveAsTable("data_profiling_results")
```

2. **JSON Export**:
```python
profiler.export_profile("sample_table", "/dbfs/FileStore/profiles/sample_table_profile.json")
```

## Best Practices

1. **Profile Generation**:
   - Run on representative data samples
   - Consider data volume
   - Monitor performance
   - Schedule regular updates

2. **Analysis**:
   - Focus on key metrics
   - Identify patterns
   - Track changes over time
   - Document insights

3. **Visualization**:
   - Choose appropriate charts
   - Use consistent formatting
   - Include clear labels
   - Highlight key findings

## Troubleshooting

Common issues and solutions:

1. **Performance Issues**:
   - Use sampling for large datasets
   - Optimize column selection
   - Monitor memory usage
   - Schedule during off-peak hours

2. **Memory Constraints**:
   - Reduce sample size
   - Process in batches
   - Clear cache regularly
   - Monitor cluster resources

3. **Visualization Issues**:
   - Check data types
   - Handle missing values
   - Scale appropriately
   - Use appropriate chart types

## Integration

The notebook can be integrated with:

1. **Data Quality Framework**:
   - Pre-profiling validation
   - Quality metric correlation
   - Issue identification

2. **ETL Processes**:
   - Data validation
   - Schema verification
   - Transformation monitoring

3. **Reporting Systems**:
   - Automated dashboards
   - Trend analysis
   - Alert generation

## Support

For issues or questions:
1. Check the execution logs
2. Review data types and formats
3. Verify memory availability
4. Contact your Databricks administrator 