# Data Quality Checks Notebook

This notebook provides a comprehensive framework for performing data quality checks on Delta tables in Databricks.

## Overview

The `DataQualityChecks.py` notebook enables you to:
- Define and execute data quality rules
- Validate data schema and completeness
- Generate quality metrics and visualizations
- Store quality check results for tracking
- Create quality dashboards

## Prerequisites

1. Access to a Databricks workspace
2. Required Python packages:
   - pyspark
   - matplotlib
   - pandas
3. Access to Delta tables for quality checks
4. Proper permissions to create and write to quality check results table

## Components

### 1. Data Quality Checker
```python
from src.data_quality.quality_checker import DataQualityChecker
checker = DataQualityChecker()
```

### 2. Quality Rules
The notebook supports various types of quality rules:
- Not null checks
- Value range validations
- Schema validations
- Completeness checks

Example rule definition:
```python
quality_rules = {
    "id_not_null": {
        "type": "not_null",
        "column": "id"
    },
    "age_range": {
        "type": "value_range",
        "column": "age",
        "min": 0,
        "max": 120
    }
}
```

## Usage

1. **Setup**:
   - Import required modules
   - Initialize Spark session
   - Create DataQualityChecker instance

2. **Load Data**:
   - Read Delta table
   - Verify data structure
   - Display sample data

3. **Define Rules**:
   - Specify quality rules
   - Configure validation parameters
   - Set thresholds

4. **Run Checks**:
   - Execute quality checks
   - Review results
   - Analyze metrics

5. **Store Results**:
   - Save check results
   - Create quality dashboard
   - Track quality metrics

## Quality Checks

### 1. Schema Validation
- Validates table structure
- Checks column existence
- Verifies data types
- Reports mismatches

### 2. Completeness Checks
- Calculates null counts
- Computes completeness ratios
- Identifies missing values
- Tracks data quality trends

### 3. Value Range Checks
- Validates numeric ranges
- Checks string patterns
- Verifies date formats
- Ensures data consistency

## Results Analysis

### 1. Schema Validation Results
```python
schema_validation = results["schema_validation"]
if not schema_validation["schema_match"]:
    print("Schema validation failed!")
    print("Missing columns:", schema_validation["missing_columns"])
    print("Extra columns:", schema_validation["extra_columns"])
    print("Type mismatches:", schema_validation["type_mismatches"])
```

### 2. Completeness Analysis
```python
completeness = results["completeness"]
for column, metrics in completeness.items():
    print(f"\nColumn: {column}")
    print(f"Total count: {metrics['total_count']}")
    print(f"Null count: {metrics['null_count']}")
    print(f"Completeness ratio: {metrics['completeness_ratio']:.2%}")
```

## Quality Dashboard

The notebook creates visualizations for:
1. **Completeness Metrics**:
   - Bar charts for column completeness
   - Trend analysis over time
   - Quality score distribution

2. **Quality Trends**:
   - Historical quality metrics
   - Improvement tracking
   - Issue identification

## Results Storage

Quality check results are stored in a Delta table:
```python
results_df = spark.createDataFrame([(str(results),)], ["quality_check_results"])
results_df.write.format("delta").mode("append").saveAsTable("quality_check_results")
```

## Best Practices

1. **Rule Definition**:
   - Start with basic validations
   - Add complex rules gradually
   - Document rule purposes
   - Set appropriate thresholds

2. **Execution**:
   - Run checks regularly
   - Monitor performance
   - Track quality trends
   - Address issues promptly

3. **Results Management**:
   - Store results systematically
   - Create quality dashboards
   - Set up alerts for issues
   - Review trends regularly

## Troubleshooting

Common issues and solutions:

1. **Performance Issues**:
   - Optimize rule complexity
   - Use appropriate partitions
   - Monitor resource usage
   - Schedule checks during off-peak hours

2. **False Positives**:
   - Review rule thresholds
   - Validate data patterns
   - Check business rules
   - Update rule definitions

3. **Missing Results**:
   - Verify data access
   - Check permissions
   - Validate rule syntax
   - Monitor execution logs

## Integration

The notebook can be integrated with:
1. **ETL Pipelines**:
   - Pre-processing validation
   - Post-processing verification
   - Quality gates

2. **Monitoring Systems**:
   - Quality alerts
   - Trend analysis
   - Issue tracking

3. **Reporting Tools**:
   - Quality dashboards
   - Executive summaries
   - Trend reports

## Support

For issues or questions:
1. Check the execution logs
2. Review rule definitions
3. Verify data access
4. Contact your Databricks administrator 