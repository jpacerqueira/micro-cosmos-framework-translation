from typing import Dict, List, Any, Optional
from pyspark.sql import DataFrame
from pyspark.sql.functions import (
    col, count, mean, stddev, min, max, 
    percentile_approx, skewness, kurtosis,
    corr, countDistinct, length
)
from pyspark.sql.types import NumericType, StringType
import json
from datetime import datetime

class DataProfiler:
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the DataProfiler with optional configuration.
        
        Args:
            config_path: Path to JSON configuration file for profiling settings
        """
        self.config = self._load_config(config_path) if config_path else {}
        self.profiling_metrics = {}

    def _load_config(self, config_path: str) -> Dict:
        """Load profiling configuration from JSON file."""
        with open(config_path, 'r') as f:
            return json.load(f)

    def profile_column(self, df: DataFrame, column: str) -> Dict[str, Any]:
        """
        Profile a single column in the DataFrame.
        
        Args:
            df: Input DataFrame
            column: Column name to profile
            
        Returns:
            Dict containing column profiling metrics
        """
        column_type = df.schema[column].dataType
        profile = {
            "column_name": column,
            "data_type": str(column_type),
            "total_count": df.count(),
            "null_count": df.filter(col(column).isNull()).count(),
            "distinct_count": df.select(column).distinct().count()
        }

        # Add type-specific metrics
        if isinstance(column_type, NumericType):
            numeric_stats = df.select(
                mean(col(column)).alias("mean"),
                stddev(col(column)).alias("stddev"),
                min(col(column)).alias("min"),
                max(col(column)).alias("max"),
                percentile_approx(col(column), 0.5).alias("median"),
                skewness(col(column)).alias("skewness"),
                kurtosis(col(column)).alias("kurtosis")
            ).collect()[0]
            
            profile.update({
                "mean": numeric_stats["mean"],
                "stddev": numeric_stats["stddev"],
                "min": numeric_stats["min"],
                "max": numeric_stats["max"],
                "median": numeric_stats["median"],
                "skewness": numeric_stats["skewness"],
                "kurtosis": numeric_stats["kurtosis"]
            })

        elif isinstance(column_type, StringType):
            # String-specific metrics
            profile.update({
                "avg_length": df.select(mean(length(col(column)))).collect()[0][0],
                "min_length": df.select(min(length(col(column)))).collect()[0][0],
                "max_length": df.select(max(length(col(column)))).collect()[0][0]
            })

        return profile

    def profile_correlations(self, df: DataFrame, numeric_columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Calculate correlations between numeric columns.
        
        Args:
            df: Input DataFrame
            numeric_columns: List of numeric columns to correlate
            
        Returns:
            Dict containing correlation matrix
        """
        if numeric_columns is None:
            numeric_columns = [
                field.name for field in df.schema.fields 
                if isinstance(field.dataType, NumericType)
            ]

        correlation_matrix = {}
        for col1 in numeric_columns:
            correlation_matrix[col1] = {}
            for col2 in numeric_columns:
                if col1 != col2:
                    correlation = df.select(corr(col(col1), col(col2))).collect()[0][0]
                    correlation_matrix[col1][col2] = correlation

        return correlation_matrix

    def profile_dataframe(self, df: DataFrame, table_name: str) -> Dict[str, Any]:
        """
        Generate comprehensive profile for entire DataFrame.
        
        Args:
            df: Input DataFrame
            table_name: Name of the table being profiled
            
        Returns:
            Dict containing complete profiling results
        """
        timestamp = datetime.now().isoformat()
        
        # Profile each column
        column_profiles = {
            column: self.profile_column(df, column)
            for column in df.columns
        }

        # Calculate correlations
        correlations = self.profile_correlations(df)

        # Generate summary statistics
        summary = {
            "table_name": table_name,
            "timestamp": timestamp,
            "row_count": df.count(),
            "column_count": len(df.columns),
            "column_profiles": column_profiles,
            "correlations": correlations
        }

        # Store metrics for tracking
        self.profiling_metrics[table_name] = summary
        
        return summary

    def get_profiling_metrics(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get stored profiling metrics for a specific table or all tables.
        
        Args:
            table_name: Optional table name to get metrics for
            
        Returns:
            Dict containing profiling metrics
        """
        if table_name:
            return self.profiling_metrics.get(table_name, {})
        return self.profiling_metrics

    def export_profile(self, table_name: str, output_path: str) -> None:
        """
        Export profiling results to a JSON file.
        
        Args:
            table_name: Name of the table to export
            output_path: Path to save the JSON file
        """
        metrics = self.get_profiling_metrics(table_name)
        with open(output_path, 'w') as f:
            json.dump(metrics, f, indent=2) 