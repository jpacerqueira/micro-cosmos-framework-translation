from pyspark.sql import SparkSession
from pyspark.sql.functions import col, current_timestamp

def main():
    # Initialize Spark Session
    spark = SparkSession.builder \
        .appName("SimpleSparkJob") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog") \
        .getOrCreate()

    try:
        # Create sample data
        data = [
            (1, "John", "Doe", 30),
            (2, "Jane", "Smith", 25),
            (3, "Bob", "Johnson", 35)
        ]
        
        # Create DataFrame
        df = spark.createDataFrame(data, ["id", "first_name", "last_name", "age"])
        
        # Add timestamp column
        df = df.withColumn("processed_at", current_timestamp())
        
        # Show the data
        print("Sample DataFrame:")
        df.show()
        
        # Perform some transformations
        transformed_df = df \
            .filter(col("age") > 25) \
            .select(
                col("id"),
                col("first_name"),
                col("last_name"),
                col("age"),
                col("processed_at")
            )
        
        print("\nTransformed DataFrame (age > 25):")
        transformed_df.show()
        
        # Write to Delta format (optional)
        # transformed_df.write.format("delta").mode("overwrite").save("/tmp/sample_data")
        
    except Exception as e:
        print(f"Error in Spark job: {str(e)}")
        raise
    finally:
        spark.stop()

if __name__ == "__main__":
    main() 