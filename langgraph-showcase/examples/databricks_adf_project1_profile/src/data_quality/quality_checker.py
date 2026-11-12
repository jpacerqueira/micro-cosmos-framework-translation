from typing import Dict, List, Any, Optional
from pyspark.sql import DataFrame
from pyspark.sql.types import StructType
from pyspark.sql.functions import col, count, when, isnan, isnull
import json
from datetime import datetime

class DataQualityChecker:
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize the DataQualityChecker with optional configuration.
        
        Args:
            config_path: Path to JSON configuration file for quality rules
        """
        self.config = self._load_config(config_path) if config_path else {}
        self.quality_metrics = {}

    def _load_config(self, config_path: str) -> Dict:
        """Load quality check configuration from JSON file."""
        with open(config_path, 'r') as f:
            return json.load(f)

    def validate_schema(self, df: DataFrame, expected_schema: StructType) -> Dict[str, Any]:
        """
        Validate DataFrame schema against expected schema.
        
        Args:
            df: Input DataFrame
            expected_schema: Expected schema to validate against
            
        Returns:
            Dict containing validation results
        """
        actual_schema = df.schema
        validation_results = {
            "schema_match": actual_schema == expected_schema,
            "missing_columns": [],
            "extra_columns": [],
            "type_mismatches": []
        }

        # Check for missing columns
        expected_fields = {field.name: field for field in expected_schema.fields}
        actual_fields = {field.name: field for field in actual_schema.fields}

        for name, field in expected_fields.items():
            if name not in actual_fields:
                validation_results["missing_columns"].append(name)
            elif field.dataType != actual_fields[name].dataType:
                validation_results["type_mismatches"].append({
                    "column": name,
                    "expected": str(field.dataType),
                    "actual": str(actual_fields[name].dataType)
                })

        # Check for extra columns
        for name in actual_fields:
            if name not in expected_fields:
                validation_results["extra_columns"].append(name)

        return validation_results

    def check_completeness(self, df: DataFrame, columns: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Check data completeness for specified columns.
        
        Args:
            df: Input DataFrame
            columns: List of columns to check (if None, checks all columns)
            
        Returns:
            Dict containing completeness metrics
        """
        if columns is None:
            columns = df.columns

        completeness_results = {}
        for column in columns:
            total_count = df.count()
            null_count = df.filter(col(column).isNull() | isnan(col(column))).count()
            completeness_results[column] = {
                "total_count": total_count,
                "null_count": null_count,
                "completeness_ratio": (total_count - null_count) / total_count
            }

        return completeness_results

    def check_data_quality(self, df: DataFrame, rules: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Run custom data quality checks based on provided rules.
        
        Args:
            df: Input DataFrame
            rules: Dictionary of quality rules to check
            
        Returns:
            Dict containing quality check results
        """
        if rules is None:
            rules = self.config.get("quality_rules", {})

        quality_results = {}
        for rule_name, rule in rules.items():
            if rule["type"] == "not_null":
                quality_results[rule_name] = self._check_not_null(df, rule["column"])
            elif rule["type"] == "unique":
                quality_results[rule_name] = self._check_unique(df, rule["column"])
            elif rule["type"] == "value_range":
                quality_results[rule_name] = self._check_value_range(
                    df, rule["column"], rule["min"], rule["max"]
                )

        return quality_results

    def _check_not_null(self, df: DataFrame, column: str) -> Dict[str, Any]:
        """Check if column contains null values."""
        null_count = df.filter(col(column).isNull() | isnan(col(column))).count()
        return {
            "null_count": null_count,
            "has_nulls": null_count > 0
        }

    def _check_unique(self, df: DataFrame, column: str) -> Dict[str, Any]:
        """Check if column values are unique."""
        total_count = df.count()
        unique_count = df.select(column).distinct().count()
        return {
            "total_count": total_count,
            "unique_count": unique_count,
            "is_unique": total_count == unique_count
        }

    def _check_value_range(self, df: DataFrame, column: str, min_val: Any, max_val: Any) -> Dict[str, Any]:
        """Check if column values are within specified range."""
        out_of_range = df.filter(
            (col(column) < min_val) | (col(column) > max_val)
        ).count()
        return {
            "out_of_range_count": out_of_range,
            "is_in_range": out_of_range == 0
        }

    def run_quality_checks(self, df: DataFrame, table_name: str) -> Dict[str, Any]:
        """
        Run all quality checks and return comprehensive results.
        
        Args:
            df: Input DataFrame
            table_name: Name of the table being checked
            
        Returns:
            Dict containing all quality check results
        """
        timestamp = datetime.now().isoformat()
        
        results = {
            "table_name": table_name,
            "timestamp": timestamp,
            "schema_validation": self.validate_schema(df, df.schema),
            "completeness": self.check_completeness(df),
            "quality_checks": self.check_data_quality(df)
        }

        # Store metrics for tracking
        self.quality_metrics[table_name] = results
        
        return results

    def get_quality_metrics(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get stored quality metrics for a specific table or all tables.
        
        Args:
            table_name: Optional table name to get metrics for
            
        Returns:
            Dict containing quality metrics
        """
        if table_name:
            return self.quality_metrics.get(table_name, {})
        return self.quality_metrics 