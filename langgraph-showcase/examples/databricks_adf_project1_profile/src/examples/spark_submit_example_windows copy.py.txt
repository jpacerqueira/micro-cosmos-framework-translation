import subprocess
import os
import sys
from pathlib import Path

def submit_spark_job(
    app_path: str,
    master: str = "local[*]",
    deploy_mode: str = "client",
    driver_memory: str = "1g",
    executor_memory: str = "1g",
    num_executors: int = 2,
    executor_cores: int = 2,
    additional_packages: list = None,
    additional_configs: dict = None,
    local_jars: list = None
) -> None:
    """
    Submit a PySpark job using spark-submit.
    
    Args:
        app_path: Path to the Python script to run
        master: Spark master URL (default: local[*])
        deploy_mode: Deploy mode (client or cluster)
        driver_memory: Driver memory allocation
        executor_memory: Executor memory allocation
        num_executors: Number of executors
        executor_cores: Number of cores per executor
        additional_packages: List of additional packages to include
        additional_configs: Dictionary of additional Spark configurations
        local_jars: List of local JAR files to include
    """
    # Get SPARK_HOME from environment using PowerShell compatible syntax
    spark_home = os.environ.get('SPARK_HOME')
    if not spark_home:
        raise EnvironmentError("SPARK_HOME environment variable is not set")

    # Convert paths to Windows format
    spark_home = str(Path(spark_home))
    app_path = str(Path(app_path))

    # Construct spark-submit command with Windows path
    spark_submit = str(Path(spark_home) / "bin" / "spark-submit.cmd")
    cmd = [
        spark_submit,
        f"--master={master}",
        f"--deploy-mode={deploy_mode}",
        f"--driver-memory={driver_memory}",
        f"--executor-memory={executor_memory}",
        f"--num-executors={num_executors}",
        f"--executor-cores={executor_cores}"
    ]

    # Add additional packages if specified
    if additional_packages:
        cmd.append(f"--packages={','.join(additional_packages)}")

    # Add local JAR files if specified
    if local_jars:
        jar_paths = [str(Path(jar)) for jar in local_jars]
        cmd.append(f"--jars={','.join(jar_paths)}")

    # Add additional configurations if specified
    if additional_configs:
        for key, value in additional_configs.items():
            cmd.append(f"--conf={key}={value}")

    # Add the application path
    cmd.append(app_path)

    try:
        # Execute spark-submit with shell=True for PowerShell compatibility
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            shell=True
        )

        # Stream output in real-time
        while True:
            output = process.stdout.readline()
            if output == '' and process.poll() is not None:
                break
            if output:
                print(output.strip())

        # Get return code
        return_code = process.poll()
        if return_code != 0:
            error = process.stderr.read()
            raise Exception(f"Spark job failed with return code {return_code}. Error: {error}")

    except Exception as e:
        print(f"Error submitting Spark job: {str(e)}")
        raise

if __name__ == "__main__":
    # Example usage with Windows path handling
    current_dir = Path(__file__).parent.parent
    example_job_path = str(current_dir / "etl_jobs" / "etl_pipeline.py")

    # Example configuration
    config = {
        "spark.executor.memory": "1g",
        "spark.driver.memory": "1g",
        "spark.executor.cores": "1",
        "spark.executor.instances": "1"
    }

    # Example packages
    packages = [
        "io.delta:delta-core_2.12:2.4.0",
        "org.apache.hadoop:hadoop-aws:3.3.4"
    ]

    # Example local JAR files
    local_jars = [
        str(Path(os.environ.get('SPARK_HOME')) / "jar" / "my_jar.jar")
    ]

    try:
        submit_spark_job(
            app_path=example_job_path,
            master="local[*]",
            deploy_mode="client",
            driver_memory="1g",
            executor_memory="1g",
            num_executors=2,
            executor_cores=2,
            additional_packages=packages,
            additional_configs=config,
            local_jars=local_jars
        )
    except Exception as e:
        print(f"Failed to submit Spark job: {str(e)}")
        sys.exit(1) 